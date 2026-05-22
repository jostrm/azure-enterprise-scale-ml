"""
Prompt Agent (Responses API) + Fabric Data Agent Tool
=====================================================

This script creates a Prompt agent version that uses the Foundry Fabric preview
tool through the Responses API. It resolves the Fabric project connection from
the current project, runs one or more questions, and validates the answers.
"""

import base64
import json
import os
import random
import string
from pathlib import Path

from dotenv import load_dotenv
from openai import AzureOpenAI, BadRequestError

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
	FabricDataAgentToolParameters,
	MicrosoftFabricPreviewTool,
	PromptAgentDefinition,
	ToolProjectConnection,
)
from azure.identity import DefaultAzureCredential


_BASE_DIR = Path(__file__).resolve().parent
load_dotenv(_BASE_DIR.parent / ".env", override=False)


def _env(key: str, default: str | None = None) -> str | None:
	value = os.getenv(key, default)
	return None if value == "<TODO>" else value


def _is_truthy(value, default=False):
	if value is None:
		return default
	return value.strip().lower() in {"1", "true", "yes", "y", "on"}


FOUNDRY_PROJECT_ENDPOINT = _env("FOUNDRY_PROJECT_ENDPOINT", "<TODO>")
CHAT_MODEL = _env("CHAT_MODEL", "<TODO>")
FABRIC_AGENT_NAME = _env("FABRIC_AGENT_NAME") or _env("FABRIC_TOOL_NAME", "fabric-dataagent")
FABRIC_TOOL_CONNECTION = _env("FABRIC_TOOL_CONNECTION")
FABRIC_WORKSPACE_ID = _env("FABRIC_WORKSPACE_ID", "<TODO>")
FABRIC_ARTIFACT_ID = _env("FABRIC_ARTIFACT_ID", "<TODO>")
FABRIC_INSTRUCTIONS = _env(
	"FABRIC_INSTRUCTIONS",
	"Always use the Fabric data agent tool to answer every question.",
)
PROJECT_CONNECTION_ID = _env("PROJECT_CONNECTION_ID")
FABRIC_TOOL_QUESTION_ARRAY = _env("FABRIC_TOOL_QUESTION_ARRAY")


def get_credential():
	auth_mode = os.getenv("AUTH_MODE", "").lower()

	if auth_mode in ["uami", "mi"]:
		managed_identity_client_id = os.getenv("AZURE_CLIENT_ID")
		allow_user_fallback = _is_truthy(os.getenv("UAMI_FALLBACK_TO_USER"), default=True)
		if not managed_identity_client_id:
			raise ValueError("AZURE_CLIENT_ID environment variable required for UAMI authentication mode")

		if allow_user_fallback:
			print("AUTH_MODE=uami: managed identity preferred; user credential fallback enabled")
			return DefaultAzureCredential(
				managed_identity_client_id=managed_identity_client_id,
				exclude_environment_credential=True,
				exclude_workload_identity_credential=True,
			)

		print("AUTH_MODE=uami: managed identity only (no user fallback)")
		return DefaultAzureCredential(
			managed_identity_client_id=managed_identity_client_id,
			exclude_cli_credential=True,
			exclude_powershell_credential=True,
			exclude_developer_cli_credential=True,
			exclude_interactive_browser_credential=True,
			exclude_shared_token_cache_credential=True,
			exclude_visual_studio_code_credential=True,
			exclude_environment_credential=True,
			exclude_workload_identity_credential=True,
		)

	if auth_mode in ["user", "interactive"]:
		return DefaultAzureCredential(
			exclude_managed_identity_credential=True,
			exclude_workload_identity_credential=True,
			exclude_environment_credential=True,
		)

	return DefaultAzureCredential()


def log_resolved_identity(credential, scope="https://management.azure.com/.default"):
	try:
		token = credential.get_token(scope).token
		payload_b64 = token.split(".")[1]
		payload_b64 += "=" * (-len(payload_b64) % 4)
		claims = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))

		print("Resolved Azure identity from DefaultAzureCredential:")
		print(f"  oid: {claims.get('oid')}")
		print(f"  upn: {claims.get('upn')}")
		print(f"  tid: {claims.get('tid')}")
		print(f"  appid: {claims.get('appid')}")
	except Exception as ex:
		print("Resolved Azure identity from DefaultAzureCredential: <unavailable>")
		print(f"  reason: {ex}")


def load_question_array() -> list[dict[str, str | None]]:
	default_questions = [
		{
			"question": "Use Fabric data agent tool. What are the sales for this year?",
			"answer": None,
		}
	]

	if not FABRIC_TOOL_QUESTION_ARRAY:
		return default_questions

	try:
		parsed = json.loads(FABRIC_TOOL_QUESTION_ARRAY)
	except json.JSONDecodeError as exc:
		raise ValueError("FABRIC_TOOL_QUESTION_ARRAY must be valid JSON.") from exc

	if not isinstance(parsed, list):
		raise ValueError("FABRIC_TOOL_QUESTION_ARRAY must be a JSON array.")

	normalized = []
	for index, item in enumerate(parsed):
		if not isinstance(item, dict):
			raise ValueError(f"FABRIC_TOOL_QUESTION_ARRAY[{index}] must be an object.")
		question = item.get("question")
		answer = item.get("answer")
		if not isinstance(question, str) or not question.strip():
			raise ValueError(f"FABRIC_TOOL_QUESTION_ARRAY[{index}].question must be a non-empty string.")
		if answer is not None and not isinstance(answer, str):
			raise ValueError(f"FABRIC_TOOL_QUESTION_ARRAY[{index}].answer must be a string or null.")
		normalized.append({"question": question, "answer": answer})

	return normalized or default_questions


def normalize_text(text: str) -> str:
	return " ".join(text.lower().split())


def validate_answer(expected: str | None, actual: str) -> bool | None:
	if expected is None:
		return None
	return normalize_text(expected) in normalize_text(actual)


def serialize_response(response) -> str:
	if hasattr(response, "model_dump_json"):
		try:
			return response.model_dump_json(indent=2)
		except Exception:
			pass
	if hasattr(response, "model_dump"):
		try:
			return json.dumps(response.model_dump(), indent=2, default=str)
		except Exception:
			pass
	if hasattr(response, "to_dict"):
		try:
			return json.dumps(response.to_dict(), indent=2, default=str)
		except Exception:
			pass
	return str(response)


def extract_response_error_details(response) -> list[str]:
	details: list[str] = []
	for item in getattr(response, "output", []) or []:
		item_type = getattr(item, "type", None)
		if item_type == "error":
			message = getattr(item, "message", None) or str(item)
			details.append(f"response.output error item: {message}")
		continue

		for content in getattr(item, "content", []) or []:
			content_type = getattr(content, "type", None)
			if content_type == "error":
				message = getattr(content, "text", None) or getattr(content, "message", None) or str(content)
				details.append(f"response.content error item: {message}")

	return details


def derive_connection_name_from_id(project_connection_id: str | None) -> str | None:
	if not project_connection_id:
		return None
	return project_connection_id.rstrip("/").split("/")[-1]


def validate_fabric_connection(connection) -> None:
	credentials = getattr(connection, "credentials", {}) or {}
	metadata = getattr(connection, "metadata", {}) or {}

	workspace_id = credentials.get("workspace-id")
	artifact_id = credentials.get("artifact-id")
	metadata_type = metadata.get("type")

	if metadata_type not in {"fabric_dataagent", "fabric_dataagent_preview"}:
		raise RuntimeError(
			f"Connection '{connection.name}' is not a supported Fabric data agent connection. "
			f"metadata.type={metadata_type!r}"
		)

	if workspace_id != FABRIC_WORKSPACE_ID:
		raise RuntimeError(
			f"Connection '{connection.name}' workspace-id mismatch. Expected {FABRIC_WORKSPACE_ID}, got {workspace_id}."
		)

	if artifact_id != FABRIC_ARTIFACT_ID:
		raise RuntimeError(
			f"Connection '{connection.name}' artifact-id mismatch. Expected {FABRIC_ARTIFACT_ID}, got {artifact_id}."
		)


def resolve_fabric_connection(project_client: AIProjectClient):
	if FABRIC_TOOL_CONNECTION:
		try:
			connection = project_client.connections.get(FABRIC_TOOL_CONNECTION, include_credentials=True)
			validate_fabric_connection(connection)
			print(f"Resolved Fabric connection from FABRIC_TOOL_CONNECTION: {connection.name}")
			return connection
		except Exception as exc:
			print(
				f"FABRIC_TOOL_CONNECTION '{FABRIC_TOOL_CONNECTION}' could not be used: {exc}"
			)
			print("Searching for an existing matching Fabric connection...")

	explicit_name = derive_connection_name_from_id(PROJECT_CONNECTION_ID)
	if explicit_name:
		try:
			connection = project_client.connections.get(explicit_name, include_credentials=True)
			validate_fabric_connection(connection)
			print(f"Resolved Fabric connection from PROJECT_CONNECTION_ID: {connection.name}")
			return connection
		except Exception as exc:
			print(
				f"PROJECT_CONNECTION_ID points to '{explicit_name}', but that connection could not be used: {exc}"
			)
			print("Searching for an existing matching Fabric connection...")

	for connection in project_client.connections.list():
		try:
			detailed = project_client.connections.get(connection.name, include_credentials=True)
			validate_fabric_connection(detailed)
			print(f"Resolved Fabric connection by credentials match: {detailed.name}")
			return detailed
		except Exception:
			continue

	raise RuntimeError(
		"No matching Fabric data agent project connection was found. "
		"The connection must exist in the Foundry project and match FABRIC_WORKSPACE_ID/FABRIC_ARTIFACT_ID."
	)


def main() -> None:
	credential = get_credential()
	log_resolved_identity(credential)

	project_client = AIProjectClient(
		endpoint=FOUNDRY_PROJECT_ENDPOINT,
		credential=credential,
	)

	fabric_connection = resolve_fabric_connection(project_client)

	salt = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
	agent_name = f"{FABRIC_AGENT_NAME}-2-{salt}"
	print(f"Using Fabric tool alias: {agent_name}")
	print(f"Fabric project connection: {fabric_connection.id}")

	fabric_tool = MicrosoftFabricPreviewTool(
		fabric_dataagent_preview=FabricDataAgentToolParameters(
			project_connections=[
				ToolProjectConnection(project_connection_id=fabric_connection.id)
			]
		)
	)

	agent = project_client.agents.create_version(
		agent_name=agent_name,
		definition=PromptAgentDefinition(
			model=CHAT_MODEL,
			instructions=FABRIC_INSTRUCTIONS,
			tools=[fabric_tool],
		),
	)
	print(f"Created/updated Fabric agent version: name={agent.name} version={agent.version}")

	responses_client: AzureOpenAI = project_client.get_openai_client()
	question_array = load_question_array()

	failures = 0
	for index, item in enumerate(question_array, start=1):
		question = item["question"]
		expected_answer = item["answer"]

		print(f"\n[{index}] Question:")
		print(question)

		try:
			response = responses_client.responses.create(
				input=[{"role": "user", "content": question}],
				extra_body={"agent_reference": {"name": agent.name, "type": "agent_reference"}},
			)
		except BadRequestError as exc:
			print("Fabric tool invocation failed.")
			print(str(exc))
			if "PowerBIUserAccessTokenNotFoundError" in str(exc):
				print(
					"The Foundry Fabric tool requires a Power BI/Fabric user access token. "
					"This usually means the current user session in Foundry portal or runtime is missing Fabric user auth."
				)
			raise

		actual_answer = response.output_text or ""
		if actual_answer.strip():
			print("Response:")
			print(actual_answer)
		else:
			print("Response: <empty>")
			error_details = extract_response_error_details(response)
			if error_details:
				print("Detected response error details:")
				for detail in error_details:
					print(f"- {detail}")
			else:
				print("No explicit error item was found in the response payload.")
			print("Raw response payload:")
			print(serialize_response(response))

		validation_result = validate_answer(expected_answer, actual_answer)
		if validation_result is None:
			print("Validation: skipped (no expected answer provided)")
		elif validation_result:
			print("Validation: PASS")
		else:
			failures += 1
			print("Validation: FAIL")
			print(f"Expected answer to contain: {expected_answer}")
			error_details = extract_response_error_details(response)
			if error_details:
				print("Detected response error details:")
				for detail in error_details:
					print(f"- {detail}")
			print("Raw response payload:")
			print(serialize_response(response))

	if failures:
		raise SystemExit(f"Validation failed for {failures} question(s).")


if __name__ == "__main__":
	main()
