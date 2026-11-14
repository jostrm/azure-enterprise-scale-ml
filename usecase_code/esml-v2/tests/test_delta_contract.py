from unittest.mock import MagicMock

import pytest

from azure_esml.domain_layer.delta import DeltaLakeTable


def test_delta_reads_real_version_as_of_not_a_directory_named_delta():
    spark = MagicMock()
    table = DeltaLakeTable("abfss://lake3@examplestorage.dfs.core.windows.net/mlops/v1/master/tables/orders")
    table.read_snapshot(spark, 4)
    spark.read.format.assert_called_once_with("delta")
    spark.read.format.return_value.option.assert_called_once_with("versionAsOf", 4)
    with pytest.raises(ValueError):
        table.read_snapshot(spark, "latest")


@pytest.mark.parametrize("path", [
    "abfss://lake3@examplestorage.dfs.core.windows.net/projects/legacy",
    "abfss://lake3@examplestorage.dfs.core.windows.net/mlops/v1/../other",
    "abfss://lake3:secret@examplestorage.dfs.core.windows.net/mlops/v1/table",
    "https://examplestorage.blob.core.windows.net/lake3/table",
    "abfss://lake3@examplestorage.dfs.core.windows.net/mlops/v1/table?sig=not-a-token",
])
def test_delta_requires_safe_explicit_shared_lake_target(path):
    with pytest.raises(ValueError):
        DeltaLakeTable(path)
