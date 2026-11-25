"""Repeatably provision the retail assets through Superset's REST API."""

import json
import sys

from common import API, BASE, DATABASE_NAME, EXTRA, asset_uuid, read_runtime, warehouse
from governance import governance

sys.path.insert(0, str(BASE / "dashboards"))
from catalog import BIG, CHART_ROWS, DATASETS, FILTERS, LINE, METRICS, NOTES, TABLE, TITLES


def candidates(api, kind, rows, field, name, uuid):
    matches = [row for row in rows if row.get(field) == name or row.get("uuid") == uuid]
    for row in matches:
        detail = api.get(kind, row["id"])
        if row.get("uuid") == uuid or detail.get("uuid") == uuid:
            return row["id"]
    # Display names of physical datasets and dashboards are unique to this project.
    if kind != "chart" and len(matches) == 1:
        return matches[0]["id"]
    return None


def register_database(api, uri):
    uid = asset_uuid("database", "olist")
    body = {
        "database_name": DATABASE_NAME, "sqlalchemy_uri": uri, "extra": EXTRA, "uuid": uid,
        "expose_in_sqllab": False, "allow_ctas": False, "allow_cvas": False,
        "allow_dml": False, "allow_file_upload": False, "allow_run_async": False,
        "cache_timeout": -1,
    }
    api.call("POST", "/database/test_connection/", {
        key: body[key] for key in ("database_name", "sqlalchemy_uri", "extra")
    })
    existing = candidates(api, "database", list(api.list("database")), "database_name", DATABASE_NAME, uid)
    return api.save("database", body, existing)


def register_datasets(api, conn, database_id):
    former = list(api.list("dataset"))
    datasets = {}
    for key, (relation, description, metrics) in DATASETS.items():
        sql = None if relation else (BASE / "datasets" / f"{key}.sql").read_text().strip()
        schema, name = relation.split(".") if relation else ("main", f"retail_{key}")
        uid = asset_uuid("dataset", key)
        selected = sql or f"SELECT * FROM {relation}"
        columns = conn.exec_driver_sql(f"DESCRIBE SELECT * FROM ({selected}) AS retail_data").all()
        dataset_id = candidates(api, "dataset", former, "table_name", name, uid)
        if dataset_id is None:
            dataset_id = api.save("dataset", {"database": database_id, "schema": schema, "table_name": name,
                                               "sql": sql, "uuid": uid})
        existing = api.get("dataset", dataset_id)
        column_ids = {x["column_name"]: x["id"] for x in existing.get("columns", [])}
        metric_ids = {x["metric_name"]: x["id"] for x in existing.get("metrics", [])}
        column_params = []
        for field, kind, *_ in columns:
            col = {"column_name": field, "type": kind, "filterable": True, "groupby": True,
                   "is_dttm": kind == "DATE" or kind.startswith("TIMESTAMP"), "is_active": True}
            if field in column_ids:
                col["id"] = column_ids[field]
            column_params.append(col)
        params = []
        for m in metrics.split():
            metric = METRICS[m]
            row = {"metric_name": m, "verbose_name": metric.label, "expression": metric.sql,
                   "description": metric.description, "metric_type":"aggregate", "d3format":metric.format}
            if m in metric_ids:
                row["id"] = metric_ids[m]
            params.append(row)
        api.save("dataset", {"database_id": database_id, "schema":schema, "table_name":name, "sql":sql,
                             "description":description, "main_dttm_col":"month_start", "columns":column_params,
                             "metrics":params, "filter_select_enabled":True, "cache_timeout":-1}, dataset_id)
        datasets[key] = {"id":dataset_id, "name":name, "schema":schema,
                         "columns":[c["column_name"] for c in column_params]}
    return datasets


def chart_params(spec, dataset_id, dashboard_id):
    first = METRICS[spec.metrics[0]]
    axes = [column for column in (spec.axis, spec.series) if column]
    timeseries = spec.axis == "month_start"
    axis_format = "~s" if spec.metrics[0] in {"gmv", "category_gmv", "freight"} else first.format
    order = [[spec.metrics[0], spec.sort == "asc"]] if spec.sort in ("asc", "desc") else (
        [[spec.axis, True]] if spec.axis else []
    )
    form = {
        "datasource": f"{dataset_id}__table", "dashboards": [dashboard_id], "viz_type": spec.viz,
        "adhoc_filters": [], "granularity_sqla": "month_start", "time_range": "No filter",
        "time_grain_sqla": "P1M", "row_limit": spec.limit, "metrics": list(spec.metrics),
        "color_scheme": "supersetColors", "number_format": first.format, "y_axis_format": axis_format,
        "x_axis_time_format": "%b %Y", "tooltipTimeFormat": "%b %Y",
        "show_legend": bool(spec.series or len(spec.metrics) > 1), "legendOrientation":"top",
        "x_axis": spec.axis, "groupby": [spec.series] if spec.series else [],
        "order_desc": spec.sort == "desc",
        "show_value": False, "rich_tooltip": True, "truncateXAxis": True,
    }
    if spec.viz == BIG:
        form.update(metric=spec.metrics[0], time_format="smart_date", header_font_size=0.36,
                    subheader_font_size=0.17, force_timestamp=False)
    elif spec.viz == TABLE:
        form.update(query_mode="aggregate", groupby=axes, page_length=10,
                    table_timestamp_format="smart_date", include_search=True, show_cell_bars=False,
                    timeseries_limit_metric=spec.metrics[0] if spec.sort in ("asc", "desc") else None,
                    column_config={m:{"d3NumberFormat":METRICS[m].format} for m in spec.metrics})
    elif spec.viz == "pie":
        form.update(metric=spec.metrics[0], groupby=axes, donut=True, show_labels=False,
                    label_type="key_percent", show_legend=False, innerRadius=45)
    elif not timeseries:
        # ECharts renders horizontal categories from the bottom up.
        form.update(orientation="horizontal", x_axis_sort=spec.axis if spec.sort == "axis" else spec.metrics[0],
                    x_axis_sort_asc=spec.sort == "desc")
        if spec.limit <= 15:
            form["x_axis_label_interval"] = 0
    query = {
        "columns": axes, "metrics": list(spec.metrics), "filters": [], "extras":{"time_grain_sqla":"P1M"},
        "orderby":order, "row_limit":spec.limit, "granularity":"month_start",
        "time_range":"No filter", "is_timeseries":timeseries,
    }
    context = {"datasource":{"id":dataset_id, "type":"table"}, "force":False, "queries":[query],
               "form_data":form, "result_type":"full", "result_format":"json"}
    return form, context


def layout(title, note, rows, panels):
    result = {
        "DASHBOARD_VERSION_KEY":"v2",
        "ROOT_ID":{"id":"ROOT_ID","type":"ROOT","children":["GRID_ID"]},
        "GRID_ID":{"id":"GRID_ID","type":"GRID","children":[],"parents":["ROOT_ID"]},
        "HEADER_ID":{"id":"HEADER_ID","type":"HEADER","meta":{"text":title}},
    }
    def row(key, items):
        rid = f"ROW-{key}"
        result["GRID_ID"]["children"].append(rid)
        result[rid] = {"id":rid, "type":"ROW", "children":[], "parents":["ROOT_ID","GRID_ID"],
                       "meta":{"background":"BACKGROUND_TRANSPARENT"}}
        for key, kind, meta in items:
            result[rid]["children"].append(key)
            result[key] = {"id":key, "type":kind, "children":[], "parents":["ROOT_ID","GRID_ID",rid],"meta":meta}

    row("context", [("MARKDOWN-context", "MARKDOWN", {"code":note, "width":12, "height":12})])
    if panels:
        row("governance", [(f"MARKDOWN-quality-{i}", "MARKDOWN",
                            {"code":body, "width":6, "height":45}) for i,body in enumerate(panels)])
    for index, charts in enumerate(rows):
        height = 19 if all(spec.viz == BIG for spec, *_ in charts) else 46
        row(f"charts-{index}", [(f"CHART-{spec.key}", "CHART",
                                 {"chartId":chart_id, "sliceName":spec.title, "uuid":uid,
                                  "width":12 // len(charts), "height":height})
                                for spec, chart_id, uid in charts])
    return result


def native_filters(slug, datasets, charts):
    def make(label, kind, target, include, description):
        included = [chart_id for spec, chart_id, _ in charts if spec.dataset in include]
        excluded = [chart_id for spec, chart_id, _ in charts if spec.dataset not in include]
        return {"id":"NATIVE_FILTER-" + asset_uuid(slug,label)[:12], "name":label, "filterType":kind,
                "targets":[target], "type":"NATIVE_FILTER", "description":description,
                "controlValues":({"enableEmptyFilter":False,"defaultToFirstItem":False,"multiSelect":True,
                                  "searchAllOptions":True,"inverseSelection":False} if target else {}),
                "defaultDataMask":{"extraFormData":{},"filterState":{},"ownState":{}}, "cascadeParentIds":[],
                "scope":{"rootPath":["ROOT_ID"],"excluded":excluded},"chartsInScope":included,"tabsInScope":[]}
    values = [make("Purchase date range", "filter_time", {}, set(datasets),
                   "Filter purchase-month buckets by their first day. Use month-aligned dates for complete months.")]
    for label, dataset, column, include in FILTERS.get(slug, ()):
        values.append(make(label,"filter_select",{"datasetId":datasets[dataset]["id"],"column":{"name":column}},
                           include,"Applies to the panels with this dimension."))
    return values


def main():
    receipt = read_runtime("snapshot.json")
    uri, engine = warehouse(receipt)
    api = API()
    db_id = register_database(api, uri)
    with engine.connect() as conn:
        datasets = register_datasets(api, conn, db_id)
        coverage, panels = governance(conn, receipt)
    engine.dispose()

    former_dashboards = list(api.list("dashboard"))
    former_charts = list(api.list("chart"))
    publication = {"version":receipt["version"],"sha256":receipt["sha256"],"database_id":db_id,
                   "datasets":datasets, "dashboards":{}}
    for slug, title in TITLES.items():
        uid = asset_uuid("dashboard", slug)
        dashboard_id = candidates(api, "dashboard", former_dashboards, "slug", slug, uid)
        base = {"dashboard_title":title, "slug":slug, "uuid":uid, "published":True}
        if dashboard_id is None:
            dashboard_id = api.save("dashboard", base)
        charts, rows = {}, []
        for chart_row in CHART_ROWS[slug]:
            row = []
            for spec in chart_row:
                dataset_id = datasets[spec.dataset]["id"]
                form, context = chart_params(spec, dataset_id, dashboard_id)
                uid = asset_uuid(slug, spec.key)
                description = " ".join(filter(None, (spec.description, *(METRICS[m].description for m in spec.metrics))))
                body = {"slice_name":spec.title, "description":description, "viz_type":spec.viz, "uuid":uid,
                        "datasource_type":"table", "datasource_id":dataset_id,"dashboards":[dashboard_id],
                        "params":json.dumps(form), "query_context":json.dumps(context), "cache_timeout":-1}
                existing = candidates(api, "chart", former_charts, "slice_name", spec.title, uid)
                chart_id = api.save("chart", body, existing)
                charts[spec.key] = {"id":chart_id, "dataset":spec.dataset, "title":spec.title}
                row.append((spec, chart_id, uid))
            rows.append(row)
        filters = native_filters(slug, datasets, [chart for row in rows for chart in row])
        metadata = {"native_filter_configuration":filters, "timed_refresh_immune_slices":[],
                    "refresh_frequency":0, "show_native_filters":True, "color_scheme":"supersetColors"}
        note = f"{NOTES[slug]}\n\n{coverage}"
        api.save("dashboard", base | {
            "position_json":json.dumps(layout(title,note,rows,panels if slug=="retail-quality" else ())),
            "json_metadata":json.dumps(metadata),
        }, dashboard_id)
        publication["dashboards"][slug] = {"title":title,"id":dashboard_id,
                                            "path":f"/superset/dashboard/{slug}/","charts":charts}
    print(json.dumps(publication, indent=2))


if __name__ == "__main__":
    main()
