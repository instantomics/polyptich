import json
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO

TABLE_SCHEMA = "polyptich.www.table"
TABLE_SCHEMA_VERSION = 1
DEFAULT_CLIENT_MAX_ROWS = 10_000
DEFAULT_CLIENT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1_000
MAX_PAGE = 1_000_000
MAX_QUERY_LENGTH = 500
MAX_JSON_ARGUMENT_LENGTH = 20_000
MAX_SORTS = 8
MAX_FILTERS = 32
MAX_PROJECTION_COLUMNS = 256
MAX_SAFE_JSON_INTEGER = 2**53 - 1

_TEXT_OPERATORS = {"contains", "starts_with", "ends_with"}
_ORDER_OPERATORS = {"gt", "gte", "lt", "lte", "between"}
_NULL_OPERATORS = {"is_null", "not_null"}
_ALL_OPERATORS = {"eq", "ne"} | _TEXT_OPERATORS | _ORDER_OPERATORS | _NULL_OPERATORS


class TableQueryError(ValueError):
    def __init__(self, message, field=None):
        super().__init__(message)
        self.field = field


@dataclass
class TableQuery:
    data_mode: str
    page: int
    page_size: int
    query: str
    sorts: list
    filters: list
    columns: list
    column_types: dict


class DataFrameCache:
    """Small process-local LRU cache invalidated by the Parquet file stat."""

    def __init__(self, max_entries=8, max_bytes=256 * 1024 * 1024):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries = OrderedDict()
        self._total_bytes = 0
        self._lock = threading.RLock()

    def get(self, path, loader):
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                return entry[0]

        frame = loader(path)
        size = _frame_size(frame, stat.st_size)
        if self.max_entries <= 0 or size > self.max_bytes:
            return frame

        with self._lock:
            for old_key in [item for item in self._entries if item[0] == str(path)]:
                _, old_size = self._entries.pop(old_key)
                self._total_bytes -= old_size
            self._entries[key] = (frame, size)
            self._total_bytes += size
            while len(self._entries) > self.max_entries or self._total_bytes > self.max_bytes:
                _, (_, removed_size) = self._entries.popitem(last=False)
                self._total_bytes -= removed_size
        return frame


def parse_query(args, column_types, *, protocol=False):
    allowed = {
        "protocol",
        "data_mode",
        "page",
        "page_size",
        "q",
        "sort",
        "filters",
        "columns",
    }
    protocol_value = _single_arg(args, "protocol", required=protocol)
    if protocol_value is not None and protocol_value != "1":
        raise TableQueryError("protocol must be 1", "protocol")
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise TableQueryError(f"Unknown table query parameter: {unknown[0]}", unknown[0])

    data_mode = _single_arg(args, "data_mode") or "auto"
    if data_mode not in {"auto", "client", "server"}:
        raise TableQueryError("data_mode must be client, server, or auto", "data_mode")
    page = _positive_integer_arg(args, "page", 1, MAX_PAGE)
    page_size = _positive_integer_arg(args, "page_size", DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE)
    query = _single_arg(args, "q") or ""
    if len(query) > MAX_QUERY_LENGTH:
        raise TableQueryError(
            f"q must not exceed {MAX_QUERY_LENGTH} characters",
            "q",
        )

    sorts = _parse_json_array(args, "sort", MAX_SORTS)
    parsed_sorts = []
    seen_sorts = set()
    for index, item in enumerate(sorts):
        if not isinstance(item, dict):
            raise TableQueryError(f"sort[{index}] must be an object", "sort")
        column = item.get("id", item.get("column"))
        _validate_column(column, column_types, f"sort[{index}].id")
        if column in seen_sorts:
            raise TableQueryError(f"sort contains duplicate column {column!r}", "sort")
        seen_sorts.add(column)
        if "direction" in item:
            direction = item["direction"]
            if direction not in {"asc", "desc"}:
                raise TableQueryError(
                    f"sort[{index}].direction must be asc or desc",
                    "sort",
                )
            descending = direction == "desc"
        else:
            descending = item.get("desc", False)
            if not isinstance(descending, bool):
                raise TableQueryError(f"sort[{index}].desc must be a boolean", "sort")
        parsed_sorts.append({"id": column, "desc": descending})

    filters = _parse_json_array(args, "filters", MAX_FILTERS)
    parsed_filters = []
    for index, item in enumerate(filters):
        if not isinstance(item, dict):
            raise TableQueryError(f"filters[{index}] must be an object", "filters")
        column = item.get("id", item.get("column"))
        _validate_column(column, column_types, f"filters[{index}].id")
        operator = item.get("operator", item.get("op"))
        if operator not in _ALL_OPERATORS:
            raise TableQueryError(
                f"filters[{index}].operator is not supported",
                "filters",
            )
        _validate_operator(operator, column_types[column], index)
        parsed = {"id": column, "operator": operator}
        if operator not in _NULL_OPERATORS:
            if "value" not in item:
                raise TableQueryError(f"filters[{index}].value is required", "filters")
            value = item["value"]
            if operator == "between" and (not isinstance(value, list) or len(value) != 2):
                raise TableQueryError(
                    f"filters[{index}].value must contain two values for between",
                    "filters",
                )
            parsed["value"] = value
        parsed_filters.append(parsed)

    projection = _parse_json_array(
        args,
        "columns",
        MAX_PROJECTION_COLUMNS,
        default=None,
    )
    if projection is not None:
        if not projection:
            raise TableQueryError("columns must contain at least one column", "columns")
        if len(set(projection)) != len(projection):
            raise TableQueryError("columns must not contain duplicates", "columns")
        for index, column in enumerate(projection):
            _validate_column(column, column_types, f"columns[{index}]")

    return TableQuery(
        data_mode=data_mode,
        page=page,
        page_size=page_size,
        query=query,
        sorts=parsed_sorts,
        filters=parsed_filters,
        columns=projection,
        column_types=column_types,
    )


def dataframe_column_types(frame):
    columns = [str(column) for column in frame.columns]
    if len(set(columns)) != len(columns):
        raise RuntimeError("Table columns must have unique string representations")
    return {name: _column_type(frame.iloc[:, index]) for index, name in enumerate(columns)}


def ensure_string_columns(frame):
    columns = [str(column) for column in frame.columns]
    if list(frame.columns) == columns:
        return frame
    result = frame.copy(deep=False)
    result.columns = columns
    return result


def table_statistics(path, component):
    row_count = _nonnegative_integer(component.get("row_count"))
    uncompressed_bytes = _nonnegative_integer(component.get("uncompressed_bytes"))
    if row_count is not None and uncompressed_bytes is not None:
        return row_count, uncompressed_bytes
    try:
        from pyarrow import parquet

        metadata = parquet.ParquetFile(path).metadata
        if row_count is None:
            row_count = metadata.num_rows
        if uncompressed_bytes is None:
            uncompressed_bytes = sum(
                metadata.row_group(row_group).column(column).total_uncompressed_size
                for row_group in range(metadata.num_row_groups)
                for column in range(metadata.num_columns)
            )
    except (ImportError, OSError, ValueError):
        pass
    return row_count, uncompressed_bytes


def choose_mode(requested, statistics, *, max_rows, max_bytes):
    if requested == "server":
        return requested
    row_count, uncompressed_bytes = statistics
    within_client_limits = (
        row_count is not None
        and uncompressed_bytes is not None
        and row_count <= max_rows
        and uncompressed_bytes <= max_bytes
    )
    if within_client_limits:
        return "client"
    return "server"


def build_envelope(frame, component_id, component, query, mode, column_types):
    total_count = len(frame)
    projection = query.columns or list(column_types)
    columns = _column_metadata(projection, component, column_types)

    if mode == "client":
        selected = frame.loc[:, projection]
        filtered_count = total_count
        page = 1
        page_size = total_count
        page_count = 1 if total_count else 0
        has_previous = False
        has_next = False
    else:
        selected = apply_query(frame, query, include_paging=False)
        filtered_count = len(selected)
        page_count = math.ceil(filtered_count / query.page_size) if filtered_count else 0
        page = min(query.page, max(1, page_count))
        start = (page - 1) * query.page_size
        selected = selected.iloc[start : start + query.page_size].loc[:, projection]
        page_size = query.page_size
        has_previous = page > 1 and filtered_count > 0
        has_next = start + len(selected) < filtered_count

    return {
        "schema": TABLE_SCHEMA,
        "schema_version": TABLE_SCHEMA_VERSION,
        "component_id": component_id,
        "mode": mode,
        "columns": columns,
        "rows": dataframe_records(selected),
        "total_count": total_count,
        "filtered_count": filtered_count,
        "page": page,
        "page_size": page_size,
        "page_count": page_count,
        "has_previous": has_previous,
        "has_next": has_next,
        "capabilities": {
            "data_modes": ["client", "server"],
            "global_filter": True,
            "column_filters": True,
            "multi_sort": True,
            "pagination": mode == "server",
            "projection": True,
            "download_formats": ["csv", "xlsx"],
            "max_page_size": MAX_PAGE_SIZE,
        },
    }


def apply_query(frame, query, *, include_paging=False):
    selected = frame
    if query.query:
        needle = query.query.casefold()
        mask = None
        for column in selected.columns:
            matches = selected[column].map(
                lambda value: False if _is_null(value) else needle in _search_text(value).casefold()
            )
            mask = matches if mask is None else mask | matches
        if mask is not None:
            selected = selected.loc[mask]

    for table_filter in query.filters:
        column = table_filter["id"]
        operator = table_filter["operator"]
        value = table_filter.get("value")
        column_type = query.column_types[column]
        try:
            mask = selected[column].map(
                lambda cell, op=operator, expected=value, value_type=column_type: _matches_filter(
                    cell, op, expected, value_type
                )
            )
        except (InvalidOperation, TypeError, ValueError) as error:
            raise TableQueryError(
                f"Invalid value for {operator} filter on column {column!r}: {error}",
                "filters",
            ) from error
        selected = selected.loc[mask]

    for sort in reversed(query.sorts):
        column = sort["id"]
        column_type = query.column_types[column]
        try:
            selected = selected.sort_values(
                column,
                ascending=not sort["desc"],
                kind="mergesort",
                na_position="last",
                key=lambda values, value_type=column_type: values.map(
                    lambda value: _sort_value(value, value_type)
                ),
            )
        except (TypeError, ValueError) as error:
            raise TableQueryError(
                f"Column {column!r} cannot be sorted: {error}",
                "sort",
            ) from error

    if include_paging:
        start = (query.page - 1) * query.page_size
        selected = selected.iloc[start : start + query.page_size]
    return selected


def dataframe_records(frame):
    columns = [str(column) for column in frame.columns]
    return [
        {column: normalize_json(value) for column, value in zip(columns, row)}
        for row in frame.itertuples(index=False, name=None)
    ]


def normalize_json(value):
    if _is_null(value):
        return None
    if hasattr(value, "as_py"):
        return normalize_json(value.as_py())
    if hasattr(value, "item") and not isinstance(value, (str, bytes, bytearray)):
        try:
            return normalize_json(value.item())
        except (TypeError, ValueError):
            pass
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value if abs(value) <= MAX_SAFE_JSON_INTEGER else str(value)
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return str(value) if value.is_finite() else None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): normalize_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [normalize_json(item) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, (str, type(None))):
        return value
    if hasattr(value, "tolist"):
        return normalize_json(value.tolist())
    return str(value)


def export_dataframe(frame, file_format):
    prepared = _prepare_export(frame)
    output = BytesIO()
    if file_format == "xlsx":
        prepared.to_excel(output, index=False)
        output.seek(0)
        return output, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if file_format == "csv":
        output.write(prepared.to_csv(index=False).encode("utf-8-sig"))
        output.seek(0)
        return output, "text/csv; charset=utf-8"
    raise ValueError(f"Unsupported table export format: {file_format}")


def _column_metadata(projection, component, column_types):
    visible = component.get("visible_columns")
    visible_set = set(visible) if isinstance(visible, list) else None
    options = component.get("column_options")
    options = options if isinstance(options, dict) else {}
    result = []
    for column in projection:
        column_type = column_types[column]
        result.append(
            {
                "id": column,
                "label": column,
                "type": column_type,
                "visible": visible_set is None or column in visible_set,
                "config": normalize_json(options.get(column, {})),
                "operators": _operators_for_type(column_type),
            }
        )
    return result


def _operators_for_type(column_type):
    operators = ["eq", "ne"]
    if column_type in {"string", "json"}:
        operators.extend(["contains", "starts_with", "ends_with"])
    if column_type in {"integer", "number", "string", "date", "datetime"}:
        operators.extend(["gt", "gte", "lt", "lte", "between"])
    operators.extend(["is_null", "not_null"])
    return operators


def _validate_operator(operator, column_type, index):
    if operator in _TEXT_OPERATORS and column_type not in {"string", "json"}:
        raise TableQueryError(
            f"filters[{index}].operator {operator!r} is not valid for {column_type}",
            "filters",
        )
    if operator in _ORDER_OPERATORS and column_type not in {
        "integer",
        "number",
        "string",
        "date",
        "datetime",
    }:
        raise TableQueryError(
            f"filters[{index}].operator {operator!r} is not valid for {column_type}",
            "filters",
        )


def _matches_filter(cell, operator, value, column_type):
    is_null = _is_null(cell)
    if operator == "is_null":
        return is_null
    if operator == "not_null":
        return not is_null
    if is_null:
        return False

    if operator in _TEXT_OPERATORS:
        cell_text = _search_text(cell).casefold()
        value_text = str(value).casefold()
        if operator == "contains":
            return value_text in cell_text
        if operator == "starts_with":
            return cell_text.startswith(value_text)
        return cell_text.endswith(value_text)

    left = _comparison_value(cell, column_type)
    if operator == "between":
        lower = _comparison_value(value[0], column_type)
        upper = _comparison_value(value[1], column_type)
        return lower <= left <= upper
    right = _comparison_value(value, column_type)
    if operator == "eq":
        return left == right
    if operator == "ne":
        return left != right
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    return left <= right


def _comparison_value(value, column_type):
    if column_type in {"integer", "number"}:
        if isinstance(value, bool):
            raise ValueError("a boolean is not a number")
        return Decimal(str(value))
    if column_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.casefold() in {"true", "false"}:
            return value.casefold() == "true"
        raise ValueError("expected true or false")
    if column_type in {"date", "datetime"}:
        import pandas as pd

        timestamp = pd.Timestamp(value)
        if column_type == "date":
            return timestamp.date()
        if timestamp.tzinfo is not None:
            return timestamp.tz_convert("UTC").value
        return timestamp.value
    if column_type == "json":
        return json.dumps(normalize_json(value), sort_keys=True, ensure_ascii=False)
    return str(value).casefold()


def _sort_value(value, column_type):
    if _is_null(value):
        return None
    return _comparison_value(value, column_type)


def _search_text(value):
    normalized = normalize_json(value)
    if isinstance(normalized, (dict, list)):
        return json.dumps(normalized, sort_keys=True, ensure_ascii=False)
    return str(normalized)


def _column_type(series):
    from pandas.api import types

    dtype = series.dtype
    if types.is_bool_dtype(dtype):
        return "boolean"
    if types.is_integer_dtype(dtype):
        return "integer"
    if types.is_numeric_dtype(dtype):
        return "number"
    if types.is_datetime64_any_dtype(dtype):
        return "datetime"
    non_null = (value for value in series if not _is_null(value))
    sample = next(non_null, None)
    if isinstance(sample, bool):
        return "boolean"
    if isinstance(sample, int):
        return "integer"
    if isinstance(sample, (float, Decimal)):
        return "number"
    if isinstance(sample, datetime):
        return "datetime"
    if isinstance(sample, date):
        return "date"
    if isinstance(sample, (dict, list, tuple, set)):
        return "json"
    if hasattr(sample, "tolist") and isinstance(sample.tolist(), (dict, list, tuple)):
        return "json"
    return "string"


def _prepare_export(frame):
    prepared = frame.copy()
    for column in prepared.columns:
        prepared[column] = prepared[column].map(_export_value)
    prepared.columns = [_spreadsheet_safe_text(str(column)) for column in prepared.columns]
    return prepared


def _export_value(value):
    if _is_null(value):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return _spreadsheet_safe_text(value)
    normalized = normalize_json(value)
    if isinstance(normalized, (dict, list)):
        return _spreadsheet_safe_text(json.dumps(normalized, sort_keys=True, ensure_ascii=False))
    if isinstance(normalized, str) and not isinstance(value, int):
        return _spreadsheet_safe_text(normalized)
    return normalized


def _spreadsheet_safe_text(value):
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r")):
        return "'" + value
    return value


def _is_null(value):
    if value is None:
        return True
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, Decimal):
        return not value.is_finite()
    try:
        import pandas as pd

        missing = pd.isna(value)
        return isinstance(missing, bool) and missing
    except (TypeError, ValueError):
        return False


def _frame_size(frame, fallback):
    try:
        return int(frame.memory_usage(index=True, deep=True).sum())
    except (AttributeError, TypeError, ValueError):
        return fallback


def _nonnegative_integer(value):
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _single_arg(args, name, required=False):
    values = args.getlist(name)
    if len(values) > 1:
        raise TableQueryError(f"{name} must be provided once", name)
    if not values:
        if required:
            raise TableQueryError(f"{name} is required", name)
        return None
    return values[0]


def _positive_integer_arg(args, name, default, maximum):
    raw = _single_arg(args, name)
    if raw in {None, ""}:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise TableQueryError(f"{name} must be an integer", name) from error
    if value < 1 or value > maximum:
        raise TableQueryError(f"{name} must be between 1 and {maximum}", name)
    return value


def _parse_json_array(args, name, maximum, default=()):
    raw = _single_arg(args, name)
    if raw is None or raw == "":
        return list(default) if default is not None else None
    if len(raw) > MAX_JSON_ARGUMENT_LENGTH:
        raise TableQueryError(
            f"{name} must not exceed {MAX_JSON_ARGUMENT_LENGTH} characters",
            name,
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise TableQueryError(f"{name} must be valid JSON", name) from error
    if not isinstance(value, list):
        raise TableQueryError(f"{name} must be a JSON array", name)
    if len(value) > maximum:
        raise TableQueryError(f"{name} must contain at most {maximum} entries", name)
    return value


def _validate_column(column, column_types, field):
    if not isinstance(column, str) or not column:
        raise TableQueryError(f"{field} must be a non-empty string", field)
    if column not in column_types:
        raise TableQueryError(f"Unknown table column: {column}", field)
