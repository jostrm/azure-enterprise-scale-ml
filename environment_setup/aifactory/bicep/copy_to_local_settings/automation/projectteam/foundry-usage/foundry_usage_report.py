#!/usr/bin/env python3
"""
Create a deployment-level Foundry, Azure OpenAI, and AI Search usage PDF.

The script is suitable for an Azure Automation Python 3 runbook when the
packages in requirements.txt are available in the Automation runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

from azure.core.exceptions import HttpResponseError
from azure.identity import DefaultAzureCredential
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.resource import ResourceManagementClient
from azure.monitor.query import LogsQueryClient
from reportlab.graphics.shapes import Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

COGNITIVE_ACCOUNT_TYPE = "microsoft.cognitiveservices/accounts"
SEARCH_SERVICE_TYPE = "microsoft.search/searchservices"
APPLICATION_INSIGHTS_TYPE = "microsoft.insights/components"

REQUEST_PATTERN = re.compile(r"(request|call|query)", re.IGNORECASE)
INPUT_TOKEN_PATTERN = re.compile(r"(input|prompt).*token", re.IGNORECASE)
OUTPUT_TOKEN_PATTERN = re.compile(r"(output|completion).*token", re.IGNORECASE)
CACHE_TOKEN_PATTERN = re.compile(r"(cache|cached|context).*token", re.IGNORECASE)
TOKEN_PATTERN = re.compile(r"token", re.IGNORECASE)


@dataclass(frozen=True)
class Resource:
    id: str
    name: str
    type: str
    kind: str


@dataclass(frozen=True)
class MetricPoint:
    resource: str
    resource_type: str
    metric: str
    deployment: str
    dimensions: str
    timestamp: datetime
    value: float


@dataclass(frozen=True)
class TelemetryPoint:
    resource: str
    deployment: str
    timestamp: datetime
    requests: float
    input_tokens: float
    output_tokens: float
    cached_tokens: float
    sessions: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a Foundry/Azure OpenAI/AI Search usage report PDF."
    )
    parser.add_argument(
        "--subscription-id",
        default=os.getenv("AZURE_SUBSCRIPTION_ID"),
        help="Azure subscription ID. Defaults to AZURE_SUBSCRIPTION_ID.",
    )
    parser.add_argument(
        "--resource-group",
        default=os.getenv("AZURE_RESOURCE_GROUP"),
        help="Resource group containing Foundry/OpenAI/Search resources.",
    )
    parser.add_argument(
        "--workspace-id",
        default=os.getenv("LOG_ANALYTICS_WORKSPACE_ID"),
        help="Log Analytics workspace customer ID. Enables telemetry/session collection.",
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        help="Inclusive report end date in YYYY-MM-DD. Defaults to today in --time-zone.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of calendar days to report, including --as-of-date (default: 30).",
    )
    parser.add_argument(
        "--time-zone",
        default="UTC",
        help="IANA time zone for hourly and daily report bucketing (default: UTC).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="PDF output path. Defaults to ./foundry-usage-YYYY-MM-DD.pdf.",
    )
    parser.add_argument(
        "--debug-json",
        default=None,
        help="Optional path for aggregated, non-identifying report data JSON.",
    )
    parser.add_argument(
        "--model-requests-output",
        default=None,
        help="Optional model request chart PDF path.",
    )
    parser.add_argument(
        "--foundry-token-output",
        default=None,
        help="Optional Foundry token chart PDF path.",
    )
    args = parser.parse_args()
    if not args.subscription_id or not args.resource_group:
        parser.error("--subscription-id and --resource-group are required.")
    if args.days < 1 or args.days > 90:
        parser.error("--days must be between 1 and 90.")
    try:
        ZoneInfo(args.time_zone)
    except Exception as error:
        parser.error(f"Invalid --time-zone '{args.time_zone}': {error}")
    if args.as_of_date:
        try:
            date.fromisoformat(args.as_of_date)
        except ValueError:
            parser.error("--as-of-date must use YYYY-MM-DD.")
    return args


def report_period(args: argparse.Namespace) -> tuple[datetime, datetime, date, ZoneInfo]:
    report_tz = ZoneInfo(args.time_zone)
    as_of = date.fromisoformat(args.as_of_date) if args.as_of_date else datetime.now(report_tz).date()
    first_day = as_of - timedelta(days=args.days - 1)
    start = datetime.combine(first_day, time.min, report_tz).astimezone(timezone.utc)
    end = datetime.combine(as_of + timedelta(days=1), time.min, report_tz).astimezone(timezone.utc)
    return start, end, as_of, report_tz


def discover_resources(
    resource_client: ResourceManagementClient, resource_group: str
) -> tuple[list[Resource], list[Resource], list[Resource]]:
    cognitive_resources: list[Resource] = []
    search_resources: list[Resource] = []
    application_insights_resources: list[Resource] = []
    for item in resource_client.resources.list_by_resource_group(resource_group):
        resource_type = (item.type or "").lower()
        resource = Resource(
            id=item.id,
            name=item.name,
            type=item.type,
            kind=item.kind or "",
        )
        if resource_type == COGNITIVE_ACCOUNT_TYPE:
            cognitive_resources.append(resource)
        elif resource_type == SEARCH_SERVICE_TYPE:
            search_resources.append(resource)
        elif resource_type == APPLICATION_INSIGHTS_TYPE:
            application_insights_resources.append(resource)
    return cognitive_resources, search_resources, application_insights_resources


def metric_category(metric_name: str, resource_type: str) -> Optional[str]:
    if CACHE_TOKEN_PATTERN.search(metric_name):
        return "cached_tokens"
    if INPUT_TOKEN_PATTERN.search(metric_name):
        return "input_tokens"
    if OUTPUT_TOKEN_PATTERN.search(metric_name):
        return "output_tokens"
    if TOKEN_PATTERN.search(metric_name):
        return "tokens"
    if REQUEST_PATTERN.search(metric_name):
        return "requests" if resource_type.lower() == COGNITIVE_ACCOUNT_TYPE else "search_requests"
    return None


def collect_metric_points(
    monitor_client: MonitorManagementClient,
    resource: Resource,
    start: datetime,
    end: datetime,
) -> list[MetricPoint]:
    definitions = list(monitor_client.metric_definitions.list(resource.id))
    metric_names = [
        definition.name.value
        for definition in definitions
        if definition.name and definition.name.value
        and metric_category(definition.name.value, resource.type)
    ]
    if not metric_names:
        return []

    points: list[MetricPoint] = []
    timespan = (
        f"{start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}/"
        f"{end.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    )
    for offset in range(0, len(metric_names), 20):
        names = metric_names[offset : offset + 20]
        try:
            result = monitor_client.metrics.list(
                resource.id,
                timespan=timespan,
                interval="PT1H",
                metricnames=",".join(names),
                aggregation="Total",
            )
        except HttpResponseError as error:
            print(f"Warning: could not read metrics for {resource.name}: {error}", file=sys.stderr)
            continue

        for metric in result.value or []:
            metric_name = metric.name.value if metric.name else "Unknown"
            for series in metric.timeseries or []:
                dimension_values = {
                    value.name.value: value.value
                    for value in (series.metadatavalues or [])
                    if value.name and value.name.value and value.value
                }
                deployment = next(
                    (
                        value
                        for key, value in dimension_values.items()
                        if key.lower() in {"modeldeploymentname", "deployment", "deploymentname"}
                    ),
                    resource.name,
                )
                dimensions = ", ".join(
                    f"{key}={value}" for key, value in sorted(dimension_values.items())
                )
                for row in series.data or []:
                    if row.time_stamp is None or row.total is None:
                        continue
                    points.append(
                        MetricPoint(
                            resource=resource.name,
                            resource_type=resource.type,
                            metric=metric_name,
                            deployment=deployment,
                            dimensions=dimensions,
                            timestamp=row.time_stamp.astimezone(timezone.utc),
                            value=float(row.total),
                        )
                    )
    return points


def telemetry_query(resource_ids: list[str], start: datetime, end: datetime) -> str:
    quoted_ids = ",".join(json.dumps(resource_id.lower()) for resource_id in resource_ids)
    return f"""
let StartTime = datetime({start.isoformat()});
let EndTime = datetime({end.isoformat()});
let TargetResources = dynamic([{quoted_ids}]);
union isfuzzy=true withsource=SourceTable
    (AzureDiagnostics
        | where TimeGenerated >= StartTime and TimeGenerated < EndTime
        | where tolower(ResourceProvider) == "microsoft.cognitiveservices"
        | extend Payload = parse_json(tostring(column_ifexists("properties_s", "")))),
    (AppRequests
        | where TimeGenerated >= StartTime and TimeGenerated < EndTime
        | extend Payload = todynamic(column_ifexists("customDimensions", dynamic({{}})))),
    (AppTraces
        | where TimeGenerated >= StartTime and TimeGenerated < EndTime
        | extend Payload = todynamic(column_ifexists("customDimensions", dynamic({{}}))))
| extend AppInsightsResourceId = tostring(column_ifexists("_ResourceId", ""))
| extend DiagnosticResourceId = tostring(column_ifexists("ResourceId", ""))
| extend ResourceId = iff(
    isnotempty(AppInsightsResourceId), AppInsightsResourceId, DiagnosticResourceId)
| where array_index_of(TargetResources, tolower(ResourceId)) >= 0
| extend Deployment = coalesce(
    tostring(Payload["modelDeploymentName"]),
    tostring(Payload["deploymentName"]),
    tostring(Payload["deployment"]),
    tostring(Payload["model"]),
    "Unspecified")
| extend RequestCount = tolong(coalesce(
    Payload["requestCount"], Payload["requests"], iif(SourceTable == "AppRequests", 1, 0)))
| extend InputTokens = todouble(coalesce(
    Payload["inputTokens"], Payload["promptTokens"], Payload["input_tokens"], 0))
| extend OutputTokens = todouble(coalesce(
    Payload["outputTokens"], Payload["completionTokens"], Payload["output_tokens"], 0))
| extend CachedTokens = todouble(coalesce(
    Payload["cachedTokens"], Payload["cacheReadInputTokens"], Payload["cached_tokens"], 0))
| extend Session = coalesce(
    tostring(column_ifexists("session_Id", "")),
    tostring(Payload["sessionId"]),
    tostring(Payload["clientSessionId"]),
    tostring(Payload["userId"]))
| summarize
    Requests = sum(RequestCount),
    InputTokens = sum(InputTokens),
    OutputTokens = sum(OutputTokens),
    CachedTokens = sum(CachedTokens),
    UniqueSessions = dcountif(Session, isnotempty(Session))
    by Hour = bin(TimeGenerated, 1h), ResourceId, Deployment
| order by Hour asc
"""


def collect_telemetry(
    logs_client: LogsQueryClient,
    workspace_id: str,
    resources: list[Resource],
    start: datetime,
    end: datetime,
) -> list[TelemetryPoint]:
    if not resources:
        return []
    try:
        response = logs_client.query_workspace(
            workspace_id=workspace_id,
            query=telemetry_query([resource.id for resource in resources], start, end),
            timespan=(start, end),
        )
    except HttpResponseError as error:
        print(f"Warning: Log Analytics telemetry query failed: {error}", file=sys.stderr)
        return []
    if not response.tables:
        return []

    points: list[TelemetryPoint] = []
    for row in response.tables[0].rows:
        values = dict(zip((column.name for column in response.tables[0].columns), row))
        timestamp = values.get("Hour")
        if not isinstance(timestamp, datetime):
            continue
        resource_id = str(values.get("ResourceId", ""))
        resource = next(
            (item.name for item in resources if item.id.lower() == resource_id.lower()),
            resource_id.rsplit("/", 1)[-1] or "Unknown",
        )
        points.append(
            TelemetryPoint(
                resource=resource,
                deployment=str(values.get("Deployment") or "Unspecified"),
                timestamp=timestamp.astimezone(timezone.utc),
                requests=float(values.get("Requests") or 0),
                input_tokens=float(values.get("InputTokens") or 0),
                output_tokens=float(values.get("OutputTokens") or 0),
                cached_tokens=float(values.get("CachedTokens") or 0),
                sessions=float(values.get("UniqueSessions") or 0),
            )
        )
    return points


def local_bucket(timestamp: datetime, report_tz: ZoneInfo, granularity: str) -> str:
    local = timestamp.astimezone(report_tz)
    return local.strftime("%Y-%m-%d %H:00") if granularity == "hour" else local.strftime("%Y-%m-%d")


def summarize_metrics(
    points: Iterable[MetricPoint], report_tz: ZoneInfo, granularity: str
) -> dict[tuple[str, str, str], dict[str, float]]:
    summary: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for point in points:
        category = metric_category(point.metric, point.resource_type)
        if not category:
            continue
        summary[(local_bucket(point.timestamp, report_tz, granularity), point.resource, point.deployment)][
            category
        ] += point.value
    return summary


def summarize_telemetry(
    points: Iterable[TelemetryPoint], report_tz: ZoneInfo, granularity: str
) -> dict[tuple[str, str, str], dict[str, float]]:
    summary: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    session_values: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for point in points:
        key = (local_bucket(point.timestamp, report_tz, granularity), point.resource, point.deployment)
        values = summary[key]
        values["requests"] += point.requests
        values["input_tokens"] += point.input_tokens
        values["output_tokens"] += point.output_tokens
        values["cached_tokens"] += point.cached_tokens
        session_values[key].append(point.sessions)
    for key, values in summary.items():
        # dcount is non-additive. Per-hour values are summed only to show activity,
        # never represented as a true period-wide distinct-session total.
        values["sessions"] = sum(session_values[key])
    return summary


def combine_summaries(
    metrics: dict[tuple[str, str, str], dict[str, float]],
    telemetry: dict[tuple[str, str, str], dict[str, float]],
) -> dict[tuple[str, str, str], dict[str, float]]:
    combined: dict[tuple[str, str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for source in (metrics, telemetry):
        for key, values in source.items():
            for category, value in values.items():
                # Metrics are authoritative for request/token totals. Telemetry fills
                # only categories absent from Metrics, primarily unique sessions.
                if category == "sessions" or category not in combined[key]:
                    combined[key][category] += value
                elif source is telemetry and combined[key][category] == 0:
                    combined[key][category] += value
    return combined


def render_table(
    rows: list[list[str]], widths: list[float], include_header: bool = True
) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if include_header else 0, hAlign="LEFT")
    styles = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if include_header:
        styles += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003C71")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    table.setStyle(TableStyle(styles))
    return table


def number(value: float) -> str:
    return f"{value:,.0f}"


def display_time_zone(time_zone_name: str) -> str:
    return "CET" if time_zone_name == "Europe/Berlin" else time_zone_name


def service_group(resource: Resource) -> str:
    return "OpenAI" if "openai" in resource.kind.lower() else "Foundry"


def daily_service_values(
    combined_daily: dict[tuple[str, str, str], dict[str, float]],
    cognitive_resources: list[Resource],
    day_labels: list[str],
    categories: list[str],
) -> dict[str, list[float]]:
    resource_groups = {resource.name: service_group(resource) for resource in cognitive_resources}
    daily_values = {
        "Foundry": {day_label: 0.0 for day_label in day_labels},
        "OpenAI": {day_label: 0.0 for day_label in day_labels},
    }
    for (day_label, resource, _), values in combined_daily.items():
        group = resource_groups.get(resource)
        if group and day_label in daily_values[group]:
            if categories == ["token_usage"]:
                component_total = (
                    values["input_tokens"] + values["output_tokens"] + values["cached_tokens"]
                )
                daily_values[group][day_label] += (
                    component_total if component_total else values["tokens"]
                )
            else:
                daily_values[group][day_label] += sum(values[category] for category in categories)
    return {
        group: [daily_values[group][day_label] for day_label in day_labels]
        for group in ("Foundry", "OpenAI")
    }


def line_chart(
    day_labels: list[str],
    series: dict[str, list[float]],
    y_axis_label: str,
) -> Drawing:
    drawing_width = 25 * cm
    drawing_height = 13 * cm
    left = 2.3 * cm
    bottom = 2.4 * cm
    chart_width = 21.7 * cm
    chart_height = 8.2 * cm
    drawing = Drawing(drawing_width, drawing_height)
    visible_values = [value for values in series.values() for value in values]
    maximum = max(visible_values, default=0.0)
    y_maximum = maximum if maximum > 0 else 1.0
    palette = {"Foundry": colors.HexColor("#0078D4"), "OpenAI": colors.HexColor("#E66C37")}

    drawing.add(Rect(left, bottom, chart_width, chart_height, strokeColor=colors.HexColor("#9CA3AF"), fillColor=None))
    for tick in range(6):
        ratio = tick / 5
        y = bottom + chart_height * ratio
        drawing.add(Line(left, y, left + chart_width, y, strokeColor=colors.HexColor("#E5E7EB")))
        drawing.add(
            String(
                left - 0.15 * cm,
                y - 2,
                number(y_maximum * ratio),
                textAnchor="end",
                fontSize=7,
                fillColor=colors.HexColor("#374151"),
            )
        )

    drawing.add(String(0.45 * cm, bottom + chart_height / 2, y_axis_label, fontSize=8, fillColor=colors.HexColor("#374151"), angle=90))
    label_indices = sorted(set([0, len(day_labels) - 1] + list(range(0, len(day_labels), max(1, len(day_labels) // 6)))))
    for index in label_indices:
        x = left + (chart_width * index / max(1, len(day_labels) - 1))
        drawing.add(Line(x, bottom, x, bottom - 0.08 * cm, strokeColor=colors.HexColor("#6B7280")))
        drawing.add(
            String(
                x,
                bottom - 0.45 * cm,
                datetime.strptime(day_labels[index], "%Y-%m-%d").strftime("%b %d"),
                textAnchor="middle",
                fontSize=7,
                fillColor=colors.HexColor("#374151"),
            )
        )

    legend_x = left
    legend_y = bottom + chart_height + 0.8 * cm
    for series_name, values in series.items():
        color = palette[series_name]
        drawing.add(Line(legend_x, legend_y, legend_x + 0.45 * cm, legend_y, strokeColor=color, strokeWidth=2))
        drawing.add(String(legend_x + 0.6 * cm, legend_y - 3, series_name, fontSize=8, fillColor=colors.HexColor("#111827")))
        legend_x += 3.1 * cm
        points = [
            (
                left + (chart_width * index / max(1, len(values) - 1)),
                bottom + (chart_height * value / y_maximum),
            )
            for index, value in enumerate(values)
        ]
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            drawing.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.6))
        for x, y in points:
            drawing.add(Rect(x - 1.2, y - 1.2, 2.4, 2.4, strokeColor=color, fillColor=color))
    return drawing


def write_chart_pdf(
    output: Path,
    title: str,
    y_axis_label: str,
    series: dict[str, list[float]],
    day_labels: list[str],
    args: argparse.Namespace,
    as_of: date,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output),
        pagesize=landscape(A4),
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=1 * cm,
        bottomMargin=1 * cm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], textColor=colors.HexColor("#003C71")))
    has_data = any(value > 0 for values in series.values() for value in values)
    story: list[Any] = [
        Paragraph(title, styles["ReportTitle"]),
        Paragraph(
            f"Resource group: <b>{args.resource_group}</b> | "
            f"Period: <b>{as_of - timedelta(days=args.days - 1):%Y-%m-%d}</b> through "
            f"<b>{as_of:%Y-%m-%d}</b> | Timezone: <b>{display_time_zone(args.time_zone)}</b>",
            styles["Small"],
        ),
        Spacer(1, 0.45 * cm),
        line_chart(day_labels, series, y_axis_label),
    ]
    if not has_data:
        story += [
            Spacer(1, 0.15 * cm),
            Paragraph("No usage was returned for the selected period.", styles["Small"]),
        ]
    document.build(story)


def write_pdf(
    output: Path,
    combined_daily: dict[tuple[str, str, str], dict[str, float]],
    combined_hourly: dict[tuple[str, str, str], dict[str, float]],
    args: argparse.Namespace,
    as_of: date,
    cognitive_resources: list[Resource],
    search_resources: list[Resource],
    application_insights_resources: list[Resource],
    telemetry_available: bool,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output),
        pagesize=landscape(A4),
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=1 * cm,
        bottomMargin=1 * cm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], textColor=colors.HexColor("#003C71")))
    story: list[Any] = [
        Paragraph("Azure AI Factory usage report", styles["ReportTitle"]),
        Paragraph(
            f"Resource group: <b>{args.resource_group}</b> | "
            f"Period: <b>{as_of - timedelta(days=args.days - 1):%Y-%m-%d}</b> through "
            f"<b>{as_of:%Y-%m-%d}</b> | Timezone: <b>{display_time_zone(args.time_zone)}</b>",
            styles["Small"],
        ),
        Spacer(1, 0.4 * cm),
    ]
    foundry_names = ", ".join(f"{item.name} ({item.kind or 'Cognitive Services'})" for item in cognitive_resources) or "None found"
    search_names = ", ".join(item.name for item in search_resources) or "None found"
    application_insights_names = ", ".join(item.name for item in application_insights_resources) or "None found"
    story += [
        Paragraph(f"<b>Foundry/Azure OpenAI resources:</b> {foundry_names}", styles["Small"]),
        Paragraph(f"<b>Azure AI Search resources:</b> {search_names}", styles["Small"]),
        Paragraph(f"<b>Application Insights resources:</b> {application_insights_names}", styles["Small"]),
        Paragraph(
            "<b>Data sources:</b> Azure Monitor metrics"
            + (" and Log Analytics telemetry." if telemetry_available else ". Log Analytics telemetry was unavailable or returned no rows.")
            + " Metric dimensions identify deployments when exposed by the resource.",
            styles["Small"],
        ),
        Spacer(1, 0.4 * cm),
    ]

    totals: dict[tuple[str, str], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for (_, resource, deployment), values in combined_daily.items():
        for category, value in values.items():
            totals[(resource, deployment)][category] += value
    summary_rows = [["Resource", "Deployment", "Requests", "Input tokens", "Output tokens", "Cached tokens", "Sessions*"]]
    for (resource, deployment), values in sorted(totals.items()):
        summary_rows.append([
            resource,
            deployment,
            number(values["requests"] + values["search_requests"]),
            number(values["input_tokens"]),
            number(values["output_tokens"]),
            number(values["cached_tokens"]),
            number(values["sessions"]),
        ])
    if len(summary_rows) == 1:
        summary_rows.append(["No supported metrics or telemetry were returned.", "", "", "", "", "", ""])
    story += [
        Paragraph("Deployment usage summary", styles["Heading2"]),
        render_table(summary_rows, [4.0 * cm, 5.0 * cm, 2.2 * cm, 2.8 * cm, 2.8 * cm, 2.8 * cm, 2.2 * cm]),
        Paragraph("* Sessions are the sum of hourly approximate distinct-session counts and are not a period-wide unique-user count.", styles["Small"]),
        Spacer(1, 0.35 * cm),
    ]

    for title, summary in (("Daily usage", combined_daily), ("Hourly usage", combined_hourly)):
        story.append(Paragraph(title, styles["Heading2"]))
        rows = [["Period", "Resource", "Deployment", "Requests", "Input", "Output", "Cached", "Sessions"]]
        for (bucket, resource, deployment), values in sorted(summary.items()):
            rows.append([
                bucket,
                resource,
                deployment,
                number(values["requests"] + values["search_requests"]),
                number(values["input_tokens"]),
                number(values["output_tokens"]),
                number(values["cached_tokens"]),
                number(values["sessions"]),
            ])
        if len(rows) == 1:
            rows.append(["No data returned.", "", "", "", "", "", "", ""])
        story.append(render_table(rows, [3.0 * cm, 3.4 * cm, 4.5 * cm, 2.1 * cm, 2.3 * cm, 2.3 * cm, 2.3 * cm, 2.0 * cm]))
        if title == "Daily usage":
            story.append(PageBreak())

    document.build(story)


def main() -> int:
    args = parse_args()
    start, end, as_of, report_tz = report_period(args)
    output = Path(args.output) if args.output else (
        Path(__file__).resolve().parent / "output" / f"foundry-usage-{as_of.isoformat()}.pdf"
    )
    model_requests_output = Path(
        args.model_requests_output
        or output.parent / f"Model-Requests-report-{as_of.isoformat()}.pdf"
    )
    foundry_token_output = Path(
        args.foundry_token_output
        or output.parent / f"Foundry-Token-report-{as_of.isoformat()}.pdf"
    )
    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    resource_client = ResourceManagementClient(credential, args.subscription_id)
    monitor_client = MonitorManagementClient(credential, args.subscription_id)
    cognitive_resources, search_resources, application_insights_resources = discover_resources(
        resource_client, args.resource_group
    )
    all_resources = cognitive_resources + search_resources

    metric_points: list[MetricPoint] = []
    for resource in all_resources:
        metric_points.extend(collect_metric_points(monitor_client, resource, start, end))

    telemetry_points: list[TelemetryPoint] = []
    if args.workspace_id:
        telemetry_points = collect_telemetry(
            LogsQueryClient(credential),
            args.workspace_id,
            cognitive_resources + application_insights_resources,
            start,
            end,
        )
    else:
        print("Info: --workspace-id not supplied; session telemetry is not collected.", file=sys.stderr)

    metrics_daily = summarize_metrics(metric_points, report_tz, "day")
    metrics_hourly = summarize_metrics(metric_points, report_tz, "hour")
    telemetry_daily = summarize_telemetry(telemetry_points, report_tz, "day")
    telemetry_hourly = summarize_telemetry(telemetry_points, report_tz, "hour")
    combined_daily = combine_summaries(metrics_daily, telemetry_daily)
    combined_hourly = combine_summaries(metrics_hourly, telemetry_hourly)

    write_pdf(
        output,
        combined_daily,
        combined_hourly,
        args,
        as_of,
        cognitive_resources,
        search_resources,
        application_insights_resources,
        bool(telemetry_points),
    )
    day_labels = [
        (as_of - timedelta(days=offset)).isoformat()
        for offset in range(args.days - 1, -1, -1)
    ]
    write_chart_pdf(
        model_requests_output,
        "Model Requests Report",
        "Requests",
        daily_service_values(combined_daily, cognitive_resources, day_labels, ["requests"]),
        day_labels,
        args,
        as_of,
    )
    write_chart_pdf(
        foundry_token_output,
        "Foundry Token Report",
        "Tokens",
        daily_service_values(
            combined_daily,
            cognitive_resources,
            day_labels,
            ["token_usage"],
        ),
        day_labels,
        args,
        as_of,
    )
    if args.debug_json:
        Path(args.debug_json).write_text(
            json.dumps(
                {
                    "daily": {"|".join(key): value for key, value in combined_daily.items()},
                    "hourly": {"|".join(key): value for key, value in combined_hourly.items()},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"Created table report: {output.resolve()}")
    print(f"Created request chart: {model_requests_output.resolve()}")
    print(f"Created token chart: {foundry_token_output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
