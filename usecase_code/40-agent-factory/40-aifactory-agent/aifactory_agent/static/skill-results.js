(() => {
  "use strict";

  const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const title = (value) => String(value).replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase());
  const scalar = (value, key = "") => {
    if (value === null || value === undefined) return "Unknown";
    if (value === true) return "Yes";
    if (value === false) return "No";
    return key === "status" || key === "phase" || key.endsWith("_status") ? title(value) : String(value);
  };

  class FactorySkillResultRenderer {
    constructor({document}) {
      if (!document?.createElement) throw new Error("Result presentation requires a document.");
      this.document = document;
    }

    node(tag, text, className) {
      const element = this.document.createElement(tag);
      if (text !== undefined) element.textContent = text;
      if (className) element.className = className;
      return element;
    }

    raw(label, data) {
      const section = this.node("details");
      section.append(this.node("summary", label), this.node("pre", JSON.stringify(data, null, 2)));
      return section;
    }

    metadata(entries) {
      const list = this.node("dl", undefined, "result-metadata");
      for (const [key, value] of entries) {
        list.append(this.node("dt", title(key)), this.node("dd", scalar(value, key)));
      }
      return list;
    }

    fields(data, depth = 0) {
      if (!object(data) && !Array.isArray(data)) return this.node("p", scalar(data));
      if (depth >= 5) return this.raw("Nested evidence (raw data)", data);
      if (Array.isArray(data)) {
        const list = this.node("ul");
        for (const value of data) {
          const item = this.node("li");
          item.append(this.fields(value, depth + 1));
          list.append(item);
        }
        return list;
      }
      const section = this.node("div");
      const entries = Object.entries(data);
      section.append(this.metadata(entries.filter(([, value]) => !object(value) && !Array.isArray(value))));
      for (const [key, value] of entries.filter(([, value]) => object(value) || Array.isArray(value))) {
        section.append(this.node("h4", title(key)), this.fields(value, depth + 1));
      }
      return section;
    }

    table(label, headers, rows) {
      const wrapper = this.node("div", undefined, "result-table-wrap");
      wrapper.tabIndex = 0;
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("aria-label", label);
      const table = this.node("table");
      table.append(this.node("caption", label));
      const head = this.node("thead");
      const headings = this.node("tr");
      for (const label of headers) {
        const heading = this.node("th", label);
        heading.setAttribute("scope", "col");
        headings.append(heading);
      }
      head.append(headings);
      const body = this.node("tbody");
      for (const values of rows) {
        const row = this.node("tr");
        for (const value of values) row.append(this.node("td", scalar(value)));
        body.append(row);
      }
      table.append(head, body);
      wrapper.append(table);
      return wrapper;
    }

    amount(currency, value) {
      // Keep server decimal strings exact; presentation never recomputes billing totals.
      if (!/^[A-Z]{3}$/.test(currency) || typeof value !== "string" ||
          !/^[+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$/.test(value) || value.length > 64) {
        throw new Error("Invalid cost amount or currency; no zero-cost value was substituted.");
      }
      return currency + " " + value;
    }

    metric(grid, label, value, note) {
      const card = this.node("article", undefined, "result-metric");
      card.append(this.node("h4", label), this.node("strong", value));
      if (note) card.append(this.node("p", note, "muted"));
      grid.append(card);
    }

    billing(section, data, label, note, grid) {
      if (!object(data) || !object(data.totals_by_currency) || !Object.keys(data.totals_by_currency).length) {
        throw new Error("Cost totals are unavailable; absence is not zero spend.");
      }
      for (const [currency, value] of Object.entries(data.totals_by_currency)) {
        this.metric(grid, label, this.amount(currency, value), note);
      }
      section.append(this.node("h4", label + " sources and coverage"));
      const entries = Object.entries(data).filter(([key]) =>
        ["source_type", "source", "observed_at", "basis"].includes(key));
      if (data.period) {
        entries.push(["period_from", data.period.from], ["period_to", data.period.to],
          ["time_zone", data.period.time_zone]);
      }
      section.append(this.metadata(entries));
      if (Array.isArray(data.services) && data.services.length) {
        section.append(this.table("Actual cost by service", ["Service", "Amount"],
          data.services.map((row) => [row.service, this.amount(row.currency, row.amount)])));
      }
      if (object(data.actual_cutoff_by_currency)) {
        section.append(this.table("Forecast coverage and billing lag", ["Currency", "Actual cutoff", "Lag (days)"],
          Object.entries(data.actual_cutoff_by_currency).map(([currency, cutoff]) =>
            [currency, cutoff, data.actual_data_lag_days_by_currency?.[currency]])));
      }
      if (data.billing_lag_explanation) section.append(this.node("p", data.billing_lag_explanation, "muted"));
    }

    renderCost(data, target) {
      if (!object(data)) throw new Error("Cost response is unavailable.");
      const section = this.node("section", undefined, "skill-report");
      section.append(this.node("h3", "Read-only cost report"));
      section.append(this.metadata(Object.entries(data).filter(([key]) =>
        ["scope_key", "subscription_id", "resource_group", "basis"].includes(key))));
      const grid = this.node("div", undefined, "result-metrics");
      const evidence = this.node("div");
      section.append(grid);
      this.billing(evidence, data.actual_mtd, "Actual month-to-date",
        "Posted Azure charges; not measured idle use.", grid);
      if (data.azure_forecast_full_month) {
        this.billing(evidence, data.azure_forecast_full_month, "Azure full-month forecast",
          "Already includes actual costs. Do not add month-to-date again.", grid);
      }
      if (data.idle_baseline) {
        const baseline = data.idle_baseline;
        if (!object(baseline) || !Array.isArray(baseline.components)) throw new Error("Invalid idle cost coverage.");
        const subtotal = baseline.priced_fixed_subtotal === null ? null
          : this.amount(baseline.currency, baseline.priced_fixed_subtotal);
        this.metric(grid, "Partial idle fixed subtotal", scalar(subtotal),
          "Full idle total: Unknown. Usage and unpriced components are excluded.");
        evidence.append(this.node("h3", baseline.status === "partial" ? "Partial estimate" : "Estimate unavailable"));
        evidence.append(this.metadata([
          ["priced_fixed_subtotal", subtotal],
          ["full_idle_total", null], ["priced_components", baseline.priced_components],
          ["unpriced_components", baseline.unpriced_components], ["advisory_month_hours", baseline.monthly_hours],
          ["basis", baseline.basis],
        ]));
        evidence.append(this.table("Provisioned baseline components",
          ["Service", "SKU", "Region", "Quantity", "Monthly fixed estimate", "Coverage", "Usage requirements"],
          baseline.components.map((row) => [
            row.service, row.sku, row.region, row.provisioned_quantity,
            row.estimate?.monthly === null || row.estimate?.monthly === undefined ? null
              : this.amount(row.estimate.currency, row.estimate.monthly),
            title(row.estimate?.status || "unknown"), row.usage_requirements,
          ])));
        evidence.append(this.node("h4", "Assumptions"), this.fields(baseline.assumptions || []));
        if (data.inventory_source) evidence.append(this.node("h4", "Inventory source"), this.fields(data.inventory_source));
      }
      section.append(evidence, this.raw("Raw response, meter sources and full evidence", data));
      target.replaceChildren(section);
    }

    renderObservation(data, target, label = "Read-only Factory observation") {
      if (!object(data)) throw new Error("Factory observation is unavailable.");
      const section = this.node("section", undefined, "skill-report");
      section.append(this.node("h3", label), this.fields(data),
        this.raw("Raw response and full evidence", data));
      target.replaceChildren(section);
    }

    appendOperation(operation, target) {
      if (!object(operation)) throw new Error("Saved operation evidence is unavailable.");
      const section = this.node("section", undefined, "skill-report");
      const preview = operation.preview || {};
      if (preview.summary) section.append(this.node("h4", "Plan summary"), this.fields(preview.summary));
      if (operation.scope) section.append(this.node("h4", "Exact target"), this.fields(operation.scope));
      for (const key of ["effects", "warnings"]) {
        if (preview[key]) section.append(this.node("h4", title(key)), this.fields(preview[key]));
      }
      if (operation.affected_resources) {
        section.append(this.node("h4", "Affected resources"), this.fields(operation.affected_resources));
      }
      if (operation.progress) {
        section.append(this.metadata([["successful_completion", operation.status === "succeeded"
          && operation.progress.completion_known === true ? "Confirmed for this operation only" : "Not confirmed"]]));
        section.append(this.node("h4", "Progress"), this.fields(operation.progress));
      }
      for (const [key, label] of [["outcome", "Execution receipt"], ["observation", "Latest observation"]]) {
        if (operation[key]) section.append(this.node("h4", label), this.fields(operation[key]));
      }
      target.append(section);
    }
  }

  window.FactorySkillResultRenderer = FactorySkillResultRenderer;
})();
