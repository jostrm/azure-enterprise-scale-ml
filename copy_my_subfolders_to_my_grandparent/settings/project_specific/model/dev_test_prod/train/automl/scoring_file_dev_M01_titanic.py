# ---------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# ---------------------------------------------------------
import json
import logging
import os
import pickle
import numpy as np
import pandas as pd
import joblib

import azureml.automl.core
from azureml.automl.core.shared import logging_utilities, log_server
from azureml.telemetry import INSTRUMENTATION_KEY
from interpret_community.common.error_handling import _format_exception

from inference_schema.schema_decorators import input_schema, output_schema
from inference_schema.parameter_types.numpy_parameter_type import NumpyParameterType
from inference_schema.parameter_types.pandas_parameter_type import PandasParameterType


input_sample = pd.DataFrame({"Pclass": pd.Series([0], dtype="int64"), "Name": pd.Series(["example_value"], dtype="object"), "Sex": pd.Series(["example_value"], dtype="object"), "Age": pd.Series([0.0], dtype="float64"), "Siblings/Spouses Aboard": pd.Series([0], dtype="int64"), "Parents/Children Aboard": pd.Series([0], dtype="int64"), "Fare": pd.Series([0.0], dtype="float64")})
output_sample = np.array([0])
try:
    log_server.enable_telemetry(INSTRUMENTATION_KEY)
    log_server.set_verbosity('INFO')
    logger = logging.getLogger('azureml.automl.core.scoring_script')
except:
    pass


def init():
    global model
    # This name is model.id of model that we want to deploy deserialize the model file back
    # into a sklearn model
    model_path = os.path.join(os.getenv('AZUREML_MODEL_DIR'), 'model.pkl')
    path = os.path.normpath(model_path)
    path_split = path.split(os.sep)
    log_server.update_custom_dimensions({'model_name': path_split[-3], 'model_version': path_split[-2]})
    try:
        logger.info("Loading model from path.")
        model = joblib.load(model_path)
        logger.info("Loading successful.")
    except Exception as e:
        logging_utilities.log_traceback(e, logger)
        raise


@input_schema('data', PandasParameterType(input_sample))
@output_schema(NumpyParameterType(output_sample))
def run(data):
    try:
        probability_y = None
        result = model.predict(data)

        # ADD predict_proba - IF model supports this....need to handle that case
        if model is not None and hasattr(model, 'predict_proba') \
                and model.predict_proba is not None and data is not None:
            try:
                probability_y = model.predict_proba(data)
            except Exception as ex:
                ex_str = _format_exception(ex)
                raise ValueError("Model does not support predict_proba method for given dataset \
                    type, inner error: {}".format(ex_str))
            try:
                probability_y = convert_to_list(probability_y[:, 1]) # Change to "probability_y" if both [negative_percentage, positive_percentage]
            except Exception as ex:
                ex_str = _format_exception(ex)
                raise ValueError("Model predict_proba output of unsupported type, inner error: {}".format(ex_str))
        # predict_proba END

        return json.dumps({'result': result.tolist(), 'probability': probability_y})
    except Exception as e:
        result = str(e)
        return json.dumps({"error": result})

from scipy.sparse import issparse
def convert_to_list(df_series_or_ndarray):
    if issparse(df_series_or_ndarray):
        return df_series_or_ndarray.toarray().tolist()
    if (isinstance(df_series_or_ndarray, pd.DataFrame)):
        return df_series_or_ndarray.values.tolist()
    if (isinstance(df_series_or_ndarray, pd.Series)):
        return df_series_or_ndarray.values.tolist()
    if (isinstance(df_series_or_ndarray, np.ndarray)):
        return df_series_or_ndarray.tolist()
    return df_series_or_ndarray