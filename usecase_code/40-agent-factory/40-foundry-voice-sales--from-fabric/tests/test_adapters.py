import asyncio
import copy
import json
import subprocess
import time
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sales_agent.identity import UserIdentity
from sales_agent.gateway import FoundryGateway
from sales_agent.fabric import FabricDataAgent
from sales_agent.contracts import BASE_INSTRUCTIONS, FUNCTION_TOOL, SalesError

import httpx
from azure.ai.projects.models import AgentReference, AgentVersionDetails, FunctionTool, PromptAgentDefinition
from azure.core.exceptions import HttpResponseError
from azure.identity import CredentialUnavailableError
from azure.identity.aio import get_bearer_token_provider
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations


def settings(**overrides):
    values = {
        "tenant_id": "11111111-1111-4111-8111-111111111111",
        "subscription_id": "22222222-2222-4222-8222-222222222222",
        "expected_user": None,
        "project_endpoint": "https://example.services.ai.azure.com/api/projects/sales",
        "agent_name": "sales",
        "agent_version": "3",
        "model_deployment": "reasoning-deployment",
        "fabric_url": "https://api.fabric.microsoft.com/v1/mcp/workspaces/"
        "33333333-3333-4333-8333-333333333333/dataagents/"
        "44444444-4444-4444-8444-444444444444/agent",
        "mcp_tool_name": None,
        "mcp_question_argument": None,
        "domain_instructions": lambda: "Trusted sales domain.",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def definition(**overrides):
    values = {
        "model": settings().model_deployment,
        "instructions": BASE_INSTRUCTIONS + "\n" + settings().domain_instructions(),
        "tools": [FunctionTool(**{k: v for k, v in FUNCTION_TOOL.items() if k != "type"})],
    }
    values.update(overrides)
    return PromptAgentDefinition(**values)


def question_tool(**overrides):
    values = {
        "name": "ask_published_sales",
        "description": "Ask the published sales data agent.",
        "inputSchema": {
            "type": "object",
            "properties": {"user_question": {"type": "string", "description": "Question"}},
            "required": ["user_question"],
        },
    }
    values.update(overrides)
    return Tool(**values)


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    def account(self, **overrides):
        value = {
            "tenantId": settings().tenant_id,
            "id": settings().subscription_id,
            "user": {"name": "user@example.invalid", "type": "user"},
        }
        value.update(overrides)
        return value

    async def verify(self, account=None, **overrides):
        result = SimpleNamespace(returncode=0, stdout=json.dumps(account or self.account()),
                                 stderr="DO NOT DISCLOSE")
        with patch("sales_agent.identity.AzureCliCredential") as factory, \
                patch("sales_agent.identity.shutil.which", return_value=r"C:\Azure\az.cmd"), \
                patch("sales_agent.identity.subprocess.run", return_value=result) as run:
            factory.return_value = SimpleNamespace(close=AsyncMock())
            identity = UserIdentity(settings(**overrides))
            verified = await identity.verify()
            await identity.close()
            factory.assert_called_once_with(tenant_id=settings().tenant_id,
                                            subscription=settings().subscription_id)
            factory.return_value.close.assert_awaited_once()
            args = run.call_args.args[0]
            self.assertEqual(args, [r"C:\Azure\az.cmd", "account", "show", "--subscription",
                                    settings().subscription_id, "--output", "json",
                                    "--only-show-errors"])
            self.assertFalse(run.call_args.kwargs.get("shell", False))
            self.assertLessEqual(run.call_args.kwargs["timeout"], 30)
            return verified

    async def test_cli_user_and_explicit_tenant_subscription_are_verified(self):
        result = await self.verify(expected_user="USER@EXAMPLE.INVALID")
        self.assertEqual(result, {"tenant": settings().tenant_id,
                                  "subscription": settings().subscription_id,
                                  "user": "user@example.invalid"})

    async def test_service_principal_managed_identity_and_wrong_account_fail(self):
        cases = [
            self.account(user={"name": "app", "type": "servicePrincipal"}),
            self.account(user={"name": "managed", "type": "managedIdentity"}),
            self.account(tenantId="55555555-5555-4555-8555-555555555555"),
            self.account(id="66666666-6666-4666-8666-666666666666"),
            self.account(user={"type": "user"}),
        ]
        for account in cases:
            with self.subTest(account=account), self.assertRaises(SalesError):
                await self.verify(account)
        with self.assertRaises(SalesError):
            await self.verify(expected_user="another@example.invalid")

    async def test_cli_errors_are_sanitized_without_login_or_fallback(self):
        failures = [
            SimpleNamespace(returncode=1, stdout="", stderr="SECRET PROVIDER OUTPUT"),
            SimpleNamespace(returncode=0, stdout="SECRET malformed", stderr=""),
        ]
        with patch("sales_agent.identity.AzureCliCredential"), \
                patch("sales_agent.identity.shutil.which", return_value="az"):
            for failure in failures:
                with patch("sales_agent.identity.subprocess.run", return_value=failure), \
                        self.assertRaises(SalesError) as caught:
                    await UserIdentity(settings()).verify()
                self.assertNotIn("SECRET", str(caught.exception))
            with patch("sales_agent.identity.subprocess.run",
                       side_effect=subprocess.TimeoutExpired("az", 15)), \
                    self.assertRaises(SalesError):
                await UserIdentity(settings()).verify()

    async def test_cli_missing_fails_without_spawning(self):
        with patch("sales_agent.identity.AzureCliCredential"), \
                patch("sales_agent.identity.shutil.which", return_value=None), \
                patch("sales_agent.identity.subprocess.run") as run, \
                self.assertRaises(SalesError):
            await UserIdentity(settings()).verify()
        run.assert_not_called()

    async def test_first_verified_user_is_pinned_and_later_switch_is_rejected(self):
        accounts = [
            self.account(),
            self.account(user={"name": "USER@EXAMPLE.INVALID", "type": "user"}),
            self.account(user={"name": "another@example.invalid", "type": "user"}),
            self.account(),
        ]
        results = [SimpleNamespace(returncode=0, stdout=json.dumps(account), stderr="")
                   for account in accounts]
        with patch("sales_agent.identity.AzureCliCredential"), \
                patch("sales_agent.identity.shutil.which", return_value="az"), \
                patch("sales_agent.identity.subprocess.run", side_effect=results):
            identity = UserIdentity(settings())
            self.assertEqual((await identity.verify())["user"], "user@example.invalid")
            self.assertEqual((await identity.verify())["user"], "USER@EXAMPLE.INVALID")
            with self.assertRaises(SalesError):
                await identity.verify()
            self.assertEqual((await identity.verify())["user"], "user@example.invalid")
            self.assertEqual(identity.verified_user, "user@example.invalid")

    async def test_failed_verification_does_not_pin_an_invalid_user(self):
        accounts = [
            self.account(tenantId="55555555-5555-4555-8555-555555555555",
                         user={"name": "wrong@example.invalid", "type": "user"}),
            self.account(),
        ]
        results = [SimpleNamespace(returncode=0, stdout=json.dumps(account), stderr="")
                   for account in accounts]
        with patch("sales_agent.identity.AzureCliCredential"), \
                patch("sales_agent.identity.shutil.which", return_value="az"), \
                patch("sales_agent.identity.subprocess.run", side_effect=results):
            identity = UserIdentity(settings())
            with self.assertRaises(SalesError):
                await identity.verify()
            self.assertEqual((await identity.verify())["user"], "user@example.invalid")
            self.assertEqual(identity.verified_user, "user@example.invalid")

    async def test_each_token_acquisition_reverifies_and_rejects_midturn_user_switch(self):
        accounts = [
            self.account(),
            self.account(),
            self.account(user={"name": "another@example.invalid", "type": "user"}),
        ]
        results = [SimpleNamespace(returncode=0, stdout=json.dumps(account), stderr="")
                   for account in accounts]
        token = SimpleNamespace(token="offline-token", expires_on=int(time.time()) + 3600)
        raw = SimpleNamespace(get_token=AsyncMock(return_value=token), close=AsyncMock())
        with patch("sales_agent.identity.AzureCliCredential", return_value=raw) as factory, \
                patch("sales_agent.identity.shutil.which", return_value="az"), \
                patch("sales_agent.identity.subprocess.run", side_effect=results) as run:
            identity = UserIdentity(settings())
            self.assertIs(await identity.credential.get_token("https://ai.azure.com/.default"), token)
            self.assertIs(await identity.credential.get_token("https://api.fabric.microsoft.com/.default"), token)
            with self.assertRaises(SalesError):
                await identity.credential.get_token("https://api.fabric.microsoft.com/.default")
            self.assertEqual(run.call_count, 3)
            self.assertEqual(raw.get_token.await_count, 2)
            factory.assert_called_once_with(tenant_id=settings().tenant_id,
                                            subscription=settings().subscription_id)
            await identity.close()
            raw.close.assert_awaited_once()

    async def test_token_proxy_verifies_before_token_and_forwards_sdk_kwargs_without_fallback(self):
        raw = SimpleNamespace(
            get_token=AsyncMock(side_effect=CredentialUnavailableError("claims challenge")),
            close=AsyncMock(),
        )
        events = []

        async def verify():
            events.append("verify")

        async def get_token(*scopes, **kwargs):
            events.append("token")
            raise CredentialUnavailableError("claims challenge")

        raw.get_token.side_effect = get_token
        with patch("sales_agent.identity.AzureCliCredential", return_value=raw):
            identity = UserIdentity(settings())
            identity.verify = AsyncMock(side_effect=verify)
            with self.assertRaises(CredentialUnavailableError):
                await identity.credential.get_token(
                    "https://ai.azure.com/.default", claims="offline-claims", enable_cae=True,
                )
            self.assertEqual(events, ["verify", "token"])
            raw.get_token.assert_awaited_once_with(
                "https://ai.azure.com/.default", claims="offline-claims", enable_cae=True,
            )

    async def test_verified_proxy_is_compatible_with_actual_azure_async_bearer_provider(self):
        token = SimpleNamespace(token="offline-token", expires_on=int(time.time()) + 3600)
        raw = SimpleNamespace(get_token=AsyncMock(return_value=token), close=AsyncMock())
        account = SimpleNamespace(returncode=0, stdout=json.dumps(self.account()), stderr="")
        with patch("sales_agent.identity.AzureCliCredential", return_value=raw), \
                patch("sales_agent.identity.shutil.which", return_value="az"), \
                patch("sales_agent.identity.subprocess.run", return_value=account) as run:
            identity = UserIdentity(settings())
            provider = get_bearer_token_provider(identity.credential, "https://ai.azure.com/.default")
            self.assertEqual(await provider(), "offline-token")
            run.assert_called_once()
            self.assertEqual(raw.get_token.call_args.args, ("https://ai.azure.com/.default",))
            await identity.close()


class GatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.credential = SimpleNamespace(close=AsyncMock())
        self.openai = SimpleNamespace(
            conversations=SimpleNamespace(create=AsyncMock(return_value=SimpleNamespace(id="conv_1"))),
            responses=SimpleNamespace(create=AsyncMock()),
            close=AsyncMock(),
        )
        self.version = SimpleNamespace(name="sales", version="3", definition=definition())
        self.project = SimpleNamespace(
            agents=SimpleNamespace(
                get_version=AsyncMock(return_value=self.version),
                create_version=AsyncMock(return_value=SimpleNamespace(name="sales", version="4")),
            ),
            get_openai_client=MagicMock(return_value=self.openai),
            close=AsyncMock(),
        )
        self.factory = patch("sales_agent.gateway.AIProjectClient", return_value=self.project).start()
        self.addCleanup(patch.stopall)
        self.gateway = FoundryGateway(settings(), self.credential)

    async def test_lazy_clients_and_exact_version_validation_on_new_conversation(self):
        self.factory.assert_not_called()
        result = await self.gateway.create_conversation()
        self.assertEqual(result, "conv_1")
        self.project.agents.get_version.assert_awaited_once_with(agent_name="sales", agent_version="3")
        self.project.get_openai_client.assert_called_once_with(max_retries=0)
        await self.gateway.close()
        self.openai.close.assert_awaited_once()
        self.project.close.assert_awaited_once()
        self.credential.close.assert_not_awaited()

    async def test_actual_sdk_function_definition_serialization(self):
        serialized = definition().as_dict()
        self.assertEqual(serialized["kind"], "prompt")
        self.assertEqual(serialized["tools"], [FUNCTION_TOOL])
        self.assertEqual(AgentReference(name="sales", version="3").as_dict(),
                         {"type": "agent_reference", "name": "sales", "version": "3"})
        self.project.agents.get_version.return_value = AgentVersionDetails(
            name="sales", version="3", definition=definition(), status="active",
        )
        self.assertEqual((await self.gateway.validate_agent())["version"], "3")

    async def test_every_response_uses_pinned_agent_reference_not_model(self):
        response = MagicMock()
        response.model_dump.return_value = {"id": "resp_1", "status": "completed", "output": []}
        self.openai.responses.create.return_value = response
        for force, items in [(True, "Sales?"), (False, [{"type": "function_call_output",
                                                       "call_id": "call_1", "output": "{}"}])]:
            result = await self.gateway.respond("conv_1", items, force_tool=force)
            kwargs = self.openai.responses.create.call_args.kwargs
            self.assertNotIn("model", kwargs)
            self.assertEqual(kwargs["conversation"], "conv_1")
            self.assertEqual(kwargs["input"], items)
            self.assertEqual(kwargs["extra_body"], {
                "agent_reference": AgentReference(name="sales", version="3").as_dict()})
            self.assertEqual(kwargs["tool_choice"],
                             {"type": "function", "name": "query_sales_data"} if force else "auto")
            self.assertIs(kwargs["parallel_tool_calls"], False)
            self.assertTrue(0 < kwargs["max_output_tokens"] <= 16000)
            self.assertEqual(result["id"], "resp_1")
        response.model_dump.assert_called_with(mode="json")

    async def test_unknown_tool_schema_kind_and_version_are_rejected(self):
        base = definition().as_dict()
        changes = [
            {**base, "tools": []},
            {**base, "tools": base["tools"] + [{"type": "code_interpreter"}]},
            {**base, "tools": [{**base["tools"][0], "name": "delete_data"}]},
            {**base, "kind": "hosted"},
        ]
        changed_schema = copy.deepcopy(base)
        changed_schema["tools"][0]["parameters"]["properties"]["url"] = {"type": "string"}
        changes.append(changed_schema)
        for data in changes:
            self.version.definition = SimpleNamespace(as_dict=lambda d=data: d)
            with self.subTest(data=data), self.assertRaises(SalesError):
                await self.gateway.create_conversation()
        self.openai.conversations.create.assert_not_awaited()
        self.version.definition = definition()
        self.version.version = "latest"
        with self.assertRaises(SalesError):
            await self.gateway.validate_agent()
        self.version.version = "3"
        self.version.name = "another"
        with self.assertRaises(SalesError):
            await self.gateway.validate_agent()

    async def test_instruction_model_drift_warns_but_status_if_present_must_be_active(self):
        self.version.definition = definition(model="different", instructions="Different")
        result = await self.gateway.validate_agent()
        self.assertEqual(len(result["warnings"]), 2)
        self.assertNotIn("Different", json.dumps(result))
        self.version.status = "inactive"
        with self.assertRaises(SalesError):
            await self.gateway.validate_agent()

    async def test_optional_unconfigured_runtime_model_does_not_report_drift(self):
        self.gateway.settings = settings(model_deployment="")
        self.assertEqual((await self.gateway.validate_agent())["warnings"], [])

    async def test_hidden_skills_and_custom_harnesses_are_not_reviewed_execution(self):
        base = definition().as_dict()
        for additional in [{"skills": [{"name": "arbitrary_execution", "version": "1"}]},
                           {"harness": {"type": "github_copilot"}}]:
            self.version.definition = SimpleNamespace(as_dict=lambda a=additional: {**base, **a})
            with self.subTest(additional=additional), self.assertRaises(SalesError):
                await self.gateway.create_conversation()
        self.openai.conversations.create.assert_not_awaited()

    async def test_publish_uses_only_prompt_and_reviewed_function_no_resources(self):
        self.assertEqual(await self.gateway.publish(), {"name": "sales", "version": "4"})
        kwargs = self.project.agents.create_version.call_args.kwargs
        self.assertEqual(kwargs["agent_name"], "sales")
        self.assertIsInstance(kwargs["definition"], PromptAgentDefinition)
        self.assertEqual(kwargs["definition"].as_dict(), definition().as_dict())
        self.project.agents.get_version.assert_not_awaited()
        self.project.get_openai_client.assert_not_called()

    async def test_provider_failure_is_sanitized_and_cancellation_propagates(self):
        self.project.agents.get_version.side_effect = HttpResponseError("SECRET")
        with self.assertRaises(SalesError) as caught:
            await self.gateway.validate_agent()
        self.assertNotIn("SECRET", str(caught.exception))
        self.openai.responses.create.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.gateway.respond("conv_1", "Sales?", force_tool=True)


class FabricTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.credential = SimpleNamespace(get_token=AsyncMock(
            return_value=SimpleNamespace(token="not-a-real-token", expires_on=int(time.time()) + 3600)))
        self.session = SimpleNamespace(
            initialize=AsyncMock(),
            list_tools=AsyncMock(return_value=ListToolsResult(tools=[question_tool()])),
            call_tool=AsyncMock(return_value=CallToolResult(
                content=[TextContent(type="text", text='{"sales":12}')],
                structuredContent={"sales": 12})),
        )
        self.transport_calls = []

        @asynccontextmanager
        async def transport(*args, **kwargs):
            self.transport_calls.append((args, kwargs))
            yield (object(), object(), lambda: "session")

        @asynccontextmanager
        async def session(*args, **kwargs):
            yield self.session

        patch("sales_agent.fabric.streamablehttp_client", side_effect=transport).start()
        patch("sales_agent.fabric.ClientSession", side_effect=session).start()
        self.addCleanup(patch.stopall)
        self.adapter = FabricDataAgent(settings(), self.credential)

    async def test_discovery_uses_official_endpoint_scope_and_real_schema(self):
        result = await self.adapter.discover()
        self.assertEqual(result, {"name": "ask_published_sales",
                                  "question_argument": "user_question",
                                  "input_schema": question_tool().inputSchema,
                                  "endpoint": settings().fabric_url})
        self.credential.get_token.assert_awaited_once_with("https://api.fabric.microsoft.com/.default")
        self.session.initialize.assert_awaited_once()
        self.session.call_tool.assert_not_awaited()
        args, kwargs = self.transport_calls[0]
        self.assertEqual(args[0], settings().fabric_url)
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer not-a-real-token"})
        factory = kwargs["httpx_client_factory"]
        async with factory(headers=kwargs["headers"], timeout=httpx.Timeout(30), auth=None) as client:
            self.assertFalse(client.follow_redirects)

    async def test_query_preserves_content_structure_and_provenance_fresh_token_per_session(self):
        await self.adapter.discover()
        result = await self.adapter.query("Sales this month?")
        self.assertEqual(self.credential.get_token.await_count, 2)
        self.session.call_tool.assert_awaited_once_with(
            "ask_published_sales", arguments={"user_question": "Sales this month?"})
        self.assertEqual(result["endpoint"], settings().fabric_url)
        self.assertEqual(result["tool"], "ask_published_sales")
        self.assertEqual(result["content"][0]["text"], '{"sales":12}')
        self.assertEqual(result["structured_content"], {"sales": 12})

    async def test_unknown_or_multiple_tools_fail_before_query_including_pagination(self):
        for tools in [[], [question_tool(), question_tool(name="manage_data")]]:
            self.session.list_tools.return_value = ListToolsResult(tools=tools)
            with self.subTest(tools=tools), self.assertRaises(SalesError):
                await self.adapter.query("Sales?")
        self.session.list_tools.side_effect = [
            ListToolsResult(tools=[question_tool()], nextCursor="next"),
            ListToolsResult(tools=[question_tool(name="delete_data")]),
        ]
        with self.assertRaises(SalesError):
            await self.adapter.query("Sales?")
        self.assertEqual(self.session.list_tools.call_args.kwargs, {"cursor": "next"})
        self.session.call_tool.assert_not_awaited()

    async def test_pagination_is_bounded_even_for_repeated_empty_pages(self):
        self.session.list_tools.return_value = ListToolsResult(tools=[], nextCursor="again")
        with self.assertRaises(SalesError):
            await self.adapter.discover()
        self.assertLessEqual(self.session.list_tools.await_count, 10)

    async def test_unsafe_schema_and_mutating_annotations_fail(self):
        unsafe = [
            {"type": "object", "properties": {"question": {"type": "number"}}, "required": ["question"]},
            {"type": "object", "properties": {"question": {"type": "string"}}},
            {"type": "object", "properties": {"question": {"type": "string"},
                                             "delete": {"type": "boolean", "default": True}},
             "required": ["question"]},
            {"type": "object", "properties": {"question": {"type": "string"}},
             "required": ["question", "hidden"]},
            {"type": "object", "properties": {"question": {"type": "string", "default": "DELETE"}},
             "required": ["question"]},
            {"type": "object", "properties": {"question": {"$ref": "https://evil.invalid/schema"}},
             "required": ["question"]},
        ]
        tools = [question_tool(inputSchema=s) for s in unsafe] + [
            question_tool(annotations=ToolAnnotations(readOnlyHint=False)),
            question_tool(annotations=ToolAnnotations(destructiveHint=True)),
        ]
        for tool in tools:
            self.session.list_tools.return_value = ListToolsResult(tools=[tool])
            with self.subTest(tool=tool), self.assertRaises(SalesError):
                await self.adapter.query("Sales?")
        self.session.call_tool.assert_not_awaited()

    async def test_omitted_write_annotations_are_not_inferred_from_sdk_defaults(self):
        annotations = ToolAnnotations.model_construct(
            _fields_set={"title"}, title="Published sales question",
            readOnlyHint=False, destructiveHint=True,
        )
        self.session.list_tools.return_value = ListToolsResult(
            tools=[question_tool(annotations=annotations)],
        )
        result = await self.adapter.query("Sales?")
        self.assertEqual(result["structured_content"], {"sales": 12})
        self.session.call_tool.assert_awaited_once()

    async def test_optional_operator_name_and_argument_must_match_discovery(self):
        for config in [settings(mcp_tool_name="wrong"),
                       settings(mcp_question_argument="wrong")]:
            with self.assertRaises(SalesError):
                await FabricDataAgent(config, self.credential).query("Sales?")
        self.session.call_tool.assert_not_awaited()

    async def test_question_and_discovered_constraints_are_validated_before_call(self):
        for value in ["", " ", "a" * 6001, None]:
            with self.subTest(value=str(value)[:20]), self.assertRaises(SalesError):
                await self.adapter.query(value)
        schema = question_tool().inputSchema
        schema["properties"]["user_question"]["maxLength"] = 3
        self.session.list_tools.return_value = ListToolsResult(tools=[question_tool(inputSchema=schema)])
        with self.assertRaises(SalesError):
            await self.adapter.query("Sales?")
        self.session.call_tool.assert_not_awaited()

    async def test_error_empty_and_oversized_results_fail_without_truncation(self):
        results = [
            CallToolResult(content=[], isError=True),
            CallToolResult(content=[]),
            CallToolResult(content=[TextContent(type="text", text="  ")]),
            CallToolResult(content=[TextContent(type="text", text="x" * (256 * 1024))]),
        ]
        for result in results:
            self.session.call_tool.return_value = result
            with self.subTest(result=str(result)[:30]), self.assertRaises(SalesError):
                await self.adapter.query("Sales?")

    async def test_multiple_content_blocks_and_structured_only_results_are_preserved(self):
        content = [TextContent(type="text", text="part 1"), TextContent(type="text", text="part 2")]
        self.session.call_tool.return_value = CallToolResult(content=content, structuredContent={"count": 2})
        result = await self.adapter.query("Sales?")
        self.assertEqual(result["content"], [part.model_dump(mode="json") for part in content])
        self.session.call_tool.return_value = CallToolResult(content=[], structuredContent={"count": 0})
        self.assertEqual((await self.adapter.query("Sales?"))["structured_content"], {"count": 0})

    async def test_short_lived_valid_token_warns_and_service_decides_without_fallback(self):
        self.credential.get_token.return_value.expires_on = int(time.time()) + 10
        with self.assertLogs("sales_agent.fabric", level="WARNING") as logs:
            result = await self.adapter.query("Sales?")
        self.assertNotIn("not-a-real-token", str(logs.output))
        self.assertEqual(result["structured_content"], {"sales": 12})
        self.credential.get_token.assert_awaited_once()
        self.session.call_tool.assert_awaited_once()

    async def test_auth_challenge_and_transport_errors_are_sanitized_not_retried(self):
        self.credential.get_token.side_effect = CredentialUnavailableError("SECRET claims challenge")
        with self.assertRaises(SalesError) as caught:
            await self.adapter.query("Sales?")
        self.assertNotIn("SECRET", str(caught.exception))
        self.credential.get_token.assert_awaited_once()
        self.credential.get_token.side_effect = None
        self.session.initialize.side_effect = ExceptionGroup(
            "SECRET transport", [httpx.ConnectError("SECRET URL")])
        with self.assertRaises(SalesError) as caught:
            await self.adapter.query("Sales?")
        self.assertNotIn("SECRET", str(caught.exception))

    async def test_cancellation_and_unexpected_programming_errors_propagate(self):
        for error in [asyncio.CancelledError(), ValueError("programming error"),
                      ExceptionGroup("mixed", [httpx.ConnectError("network"), ValueError("bug")])]:
            self.session.initialize.side_effect = error
            with self.subTest(error=type(error)), self.assertRaises(type(error)):
                await self.adapter.query("Sales?")

    async def test_request_timeout_is_bounded_and_sanitized(self):
        async def wait():
            await asyncio.sleep(10)

        self.session.initialize.side_effect = wait
        with patch("sales_agent.fabric.REQUEST_TIMEOUT", 0.01), self.assertRaises(SalesError):
            await self.adapter.query("Sales?")
        self.session.call_tool.assert_not_awaited()


class FabricTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.credential = SimpleNamespace(get_token=AsyncMock(
            return_value=SimpleNamespace(token="not-a-real-token", expires_on=int(time.time()) + 3600)))
        self.requests = []

    def factory(self, handler):
        def make_client(**kwargs):
            return httpx.AsyncClient(**kwargs, transport=httpx.MockTransport(handler),
                                     follow_redirects=False)
        return make_client

    async def test_real_mcp_session_serializes_discovery_and_question_only(self):
        def handler(request):
            self.requests.append(request)
            if request.method == "DELETE":
                return httpx.Response(204)
            if request.method == "GET":
                return httpx.Response(405)
            message = json.loads(request.content)
            if "id" not in message:
                return httpx.Response(202)
            method = message["method"]
            if method == "initialize":
                result = {"protocolVersion": message["params"]["protocolVersion"],
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "offline-published-data-agent", "version": "1"}}
            elif method == "tools/list":
                result = ListToolsResult(tools=[question_tool()]).model_dump(mode="json", exclude_none=True)
            elif method == "tools/call":
                self.assertEqual(message["params"]["name"], "ask_published_sales")
                self.assertEqual(message["params"]["arguments"], {"user_question": "Sales?"})
                result = CallToolResult(
                    content=[TextContent(type="text", text="Verified source result")],
                    structuredContent={"sales": 12},
                ).model_dump(mode="json", exclude_none=True)
            else:
                self.fail("Unexpected MCP method: " + method)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result},
                                  headers={"Mcp-Session-Id": "offline-session"})

        with patch("sales_agent.fabric._http_client", side_effect=self.factory(handler)):
            result = await FabricDataAgent(settings(), self.credential).query("Sales?")
        self.assertEqual(result["structured_content"], {"sales": 12})
        self.assertTrue(self.requests)
        for request in self.requests:
            self.assertEqual(str(request.url), settings().fabric_url)
            self.assertEqual(request.headers["Authorization"], "Bearer not-a-real-token")

    async def test_cross_host_redirect_and_claims_challenge_never_follow_or_retry(self):
        for status, headers in [
            (307, {"Location": "https://evil.invalid/collect"}),
            (401, {"WWW-Authenticate": 'Bearer claims="SECRET_CHALLENGE"'}),
        ]:
            self.requests.clear()

            def handler(request):
                self.requests.append(request)
                return httpx.Response(status, headers=headers, text="SECRET_PROVIDER_BODY")

            with self.subTest(status=status), \
                    patch("sales_agent.fabric._http_client", side_effect=self.factory(handler)), \
                    self.assertRaises(SalesError) as caught:
                await FabricDataAgent(settings(), self.credential).query("Sales?")
            self.assertNotIn("SECRET", str(caught.exception))
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(str(self.requests[0].url), settings().fabric_url)


if __name__ == "__main__":
    unittest.main()
