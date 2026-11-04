"""Optional Spark/Delta adapter; table versions, not copied transaction-log folders."""

from dataclasses import dataclass

import re

from ml_model_factory.lake import relative_key, identifier


@dataclass(frozen=True)
class DeltaLakeTable:
    table_uri: str

    def __post_init__(self):
        from urllib.parse import urlsplit
        parsed = urlsplit(self.table_uri)
        if (parsed.scheme != "abfss" or not parsed.netloc or parsed.query or parsed.fragment
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]@[a-z0-9]{3,24}\.dfs\.core\.windows\.net", parsed.netloc)
                or not parsed.path.startswith("/mlops/v1/")):
            raise ValueError("Use an explicit credential-free abfss URI under the versioned lake namespace")
        relative_key(parsed.path.strip("/"))

    def read_snapshot(self, spark, version: int):
        if type(version) is not int or version < 0:
            raise ValueError("Pin an actual nonnegative Delta transaction version")
        return spark.read.format("delta").option("versionAsOf", version).load(self.table_uri)

    def initial(self, frame) -> dict:
        frame.write.format("delta").mode("errorifexists").save(self.table_uri)
        return self._receipt(frame.sparkSession, "initial")

    def merge(self, frame, *, primary_key: list[str], operation_column: str = "_operation") -> dict:
        from delta.tables import DeltaTable
        from pyspark.sql import functions as F

        if not primary_key or len(set(primary_key)) != len(primary_key):
            raise ValueError("Delta merge requires unique explicit primary-key columns")
        for column in [*primary_key, operation_column]:
            identifier(column, "column")
            if column not in frame.columns:
                raise ValueError(f"Missing CDC column {column}")
        keys = [F.col(key) for key in primary_key]
        invalid = F.col(operation_column).isNull() | ~F.col(operation_column).isin("upsert", "delete")
        for key in keys:
            invalid = invalid | key.isNull()
        if frame.filter(invalid).limit(1).count():
            raise ValueError("CDC keys must be present and operations must be upsert/delete")
        if frame.groupBy(*primary_key).count().filter(F.col("count") > 1).limit(1).count():
            raise ValueError("Resolve CDC ordering to one change per key before Delta merge")
        table = DeltaTable.forPath(frame.sparkSession, self.table_uri)
        target_columns = table.toDF().columns
        if set(frame.columns) - {operation_column} != set(target_columns):
            raise ValueError("Schema evolution requires an explicit new data contract")
        condition = " AND ".join(f"target.`{key}` = source.`{key}`" for key in primary_key)
        values = {name: f"source.`{name.replace('`', '``')}`" for name in target_columns}
        table.alias("target").merge(frame.alias("source"), condition).whenMatchedDelete(
            condition=f"source.`{operation_column}` = 'delete'",
        ).whenMatchedUpdate(
            condition=f"source.`{operation_column}` = 'upsert'", set=values,
        ).whenNotMatchedInsert(
            condition=f"source.`{operation_column}` = 'upsert'", values=values,
        ).execute()
        return self._receipt(frame.sparkSession, "merge")

    def _receipt(self, spark, operation) -> dict:
        return {"table_uri": self.table_uri, "operation": operation,
                "latest_observed_version": self._version(spark),
                "binding": "Observed table version; concurrent writers may have committed. Pin a reviewed version before training."}

    def _version(self, spark) -> int:
        from delta.tables import DeltaTable
        return int(DeltaTable.forPath(spark, self.table_uri).history(1).select("version").first()["version"])
