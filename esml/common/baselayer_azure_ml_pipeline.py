#region(collapsed) IMPORTS
from genericpath import exists
import os
import datetime
import shutil
from azureml.core import Experiment
from azureml.core import Model
from azureml.data.constants import NONE
from azureml.train.automl.run import AutoMLRun
# if  PipelineParameter - you can't use this technique of referring to an existing Environment. Instead, you must set the environment field of the RunConfiguration to an Environment = DONE.
from azureml.pipeline.core import PipelineParameter
from azureml.core.dataset import Dataset
from azureml.pipeline.steps import PythonScriptStep
from azureml.data import OutputFileDatasetConfig
from azureml.core import Environment
from azureml.core.runconfig import DEFAULT_CPU_IMAGE
from azureml.core.runconfig import DockerConfiguration
from azureml.core.runconfig import RunConfiguration
from azureml.core.conda_dependencies import CondaDependencies
from azureml.pipeline.core import Pipeline
from azureml.pipeline.core import StepSequence
from azureml.widgets import RunDetails
# To publish
from  azureml.pipeline.core import PipelineRun
from azureml.pipeline.core import PublishedPipeline
from azureml.pipeline.core import PipelineEndpoint
from azureml.data.dataset_error_handling import DatasetValidationError

#endregion
#region(collapsed) Enumerators
class esml_pipeline_types():
    IN_2_GOLD_SCORING = "IN_2_GOLD_SCORING"
    IN_2_GOLD = "IN_2_GOLD"
    BRONZE_2_GOLD = "BRONZE_2_GOLD"
    BRONZE_2_GOLD_SCORING = "BRONZE_2_GOLD_SCORING"
    GOLD_SCORING = "GOLD_SCORING"

class esml_step_types():
    IN_2_BRONZE = "IN_2_BRONZE"
    BRONZE_2_SILVER = "BRONZE_2_SILVER"
    IN_2_SILVER = "IN_2_SILVER"
    SILVER_MERGED_2_GOLD = "SILVER_MERGED_2_GOLD"
    SCORING_GOLD = "SCORING_GOLD"

#endregion

# ESMLPipelineFactory brings same logging for ALL models in enterprise. Uniform way of pipelines
class ESMLPipelineFactory():
    p = None
    _datalake = None
    _allow_reuse = True
    _batch_pipeline_parameters = []
    _target_column_name = None
    _esml_pipeline_type = None
    _script_names_dic = {}
    _script_template_enterprise = "../../../settings/enterprise_specific/dev_test_prod_defaults/batch/pipeline_template"
    #region(collapsed) TODO
    #script_template_user = "../../../settings/project_specific/model/dev_test_prod_override/batch/pipeline_template"
    #endregion
    _snapshot_folder = "../../../2_A_aml_pipeline/4_inference/batch/"

#region USER CUSTOMIZATION - EDIT the code in THESE files. Init files with "create_dataset_scripts_from_template()"
    _in2silver_filename = "in2silver.py"
    _silver2gold_filename = "silver_merged_2_gold.py"
    _scoring_filename = "scoring_gold.py"

    _in2bronze_filename = "in2bronze.py" # Not used in In2Silver2Gold data model
    _bronze2silver_filename = "bronze2silver.py" # Not used In2Silver2Gold data model

#endregion

# region(collapsed) INIT
    def __init__(self, project, target_column_name, esml_pipeline_type = esml_pipeline_types.IN_2_GOLD_SCORING):
        self.p = project
        self._target_column_name = target_column_name
        self._esml_pipeline_type = esml_pipeline_type
        self._snapshot_folder = self._snapshot_folder + self.p.ModelAlias+ "/" # self.p.model_folder_name
        self._create_parameters()
# endregion

#region PUBLIC Properties
    @property
    def batch_pipeline_parameters(self):
        return self._batch_pipeline_parameters
    @property
    def name_batch_pipeline(self):
        return self.p.experiment_name + "_batch_scoring_pipe"
    @property
    def name_batch_pipeline_endpoint(self):
        return self.name_batch_pipeline + "_EP"
    @property
    def experiment_name(self):
        return self.name_batch_pipeline
    @property
    def description_batch_pipeline(self):
        return "Batch scoring,{} pipeline, for label {}".format(self._esml_pipeline_type,self._target_column_name)

#endregion

#region PUBLIC Methods

    def publish_pipeline(self, pipeline, name_suffix=""):
        #name_pipeline = self.name_batch_pipeline
        name_endpoint = self.name_batch_pipeline_endpoint + name_suffix
        found_endpoint = None
        exists = False

        published_pipeline1 = pipeline.publish(name=self.name_batch_pipeline, description=self.description_batch_pipeline, continue_on_step_failure=False)

        #published_pipelines = PublishedPipeline.list(self.p.ws)
        published_endpoints = PipelineEndpoint.list(self.p.ws)
        for ep in published_endpoints:
            print ("pub_pipe.name", ep.name)
            print ("pub_pipe.id", ep.id)
            if(ep.name == name_endpoint):
                found_endpoint = ep
                exists = True
                break

        if (not exists):
            pipeline_endpoint = PipelineEndpoint.publish(
                workspace=self.p.ws,
                name=name_endpoint,
                pipeline=published_pipeline1,
                description="Endpoint:" + self.description_batch_pipeline)
            found_endpoint = pipeline_endpoint
            #pipeline_endpoint.add_default(published_pipeline1)
        else:
            found_endpoint.add_default(published_pipeline1) # pipeline_endpoint = PipelineEndpoint.get(workspace=self.p.ws, name=name_endpoint)

        return published_pipeline1, found_endpoint


    '''
    regenerate_outputs, Example:  15min run can take 3-4 seconds if data hasn't changed.
    '''
    def execute_pipeline(self, pipeline = None, pipeline_type=esml_pipeline_types.IN_2_GOLD_SCORING, pipeline_parameters = None, regenerate_outputs=True): 
        pipeline = pipeline
        parameters = None
        if(pipeline_parameters is None):
            parameters = self._batch_pipeline_parameters
        else:
            parameters = pipeline_parameters

        if(pipeline is None):
            if (pipeline_type == esml_pipeline_types.IN_2_GOLD_SCORING):
                pipeline = self.create_batch_bronze2gold_scoring_if_not_exists()
            elif(pipeline_type == esml_pipeline_types.GOLD_SCORING):
                pipeline = self.create_batch_gold_scoring_if_not_exists()

        experiment_name = self.name_batch_pipeline
        experiment = Experiment(self.p.ws,experiment_name)

        par_dic = {
            parameters[0].name: parameters[0].default_value, # esml_inference_model_version
            parameters[1].name: parameters[1].default_value,# esml_scoring_folder_date
            parameters[2].name: parameters[2].default_value, # esml_optional_unique_scoring_folder # par_esml_dev_test_prod
            parameters[3].name: parameters[3].default_value # par_esml_dev_test_prod
        }
        pipeline_run = experiment.submit(pipeline, regenerate_outputs=regenerate_outputs,pipeline_parameters=par_dic
        # ,tags={
        #        "training_run_id": best_run.id,
        #        "run_algorithm": best_run.properties["run_algorithm"],
        #        "valid_score": best_run.properties["score"],
        #        "primary_metric": best_run.properties["primary_metric"],
        #    }
        )
        print("Pipeline submitted for execution!")
        return pipeline_run

    # Copies 1-M script files from Datasets, to be edited later by user
    def print_script_files(self):
        return self.create_dataset_scripts_from_template(False,True)

    def create_dataset_scripts_from_template(self, overwrite_if_exists=False, only_info=False):
        self._script_names = {}
        old_loc = os.getcwd()
        source = self._script_template_enterprise + "/" + self._in2silver_filename
        try:
            os.chdir(os.path.dirname(__file__))
            os.makedirs(os.path.dirname( self._snapshot_folder), exist_ok=True)

            gold_test_if_exists = self._script_template_enterprise + "/" + self._scoring_filename

            if(not only_info):
                if(not overwrite_if_exists and os.path.exists(gold_test_if_exists)):
                    print ("Did NOT overwrite script-files with template-files such as '{}', since overwrite_if_exists=False".format(self._scoring_filename))
                    return # Guard
            else: # only info
                overwrite_if_exists = False # Ensure not overwriting

            if(not only_info):
                print("Creates template step_files.py for user to edit at:")

            # SILVER DATASETS
            counter = 0
            for d in self.p.Datasets:
                destination = self._snapshot_folder + d.in2silver_filename
                if(not only_info):
                    shutil.copy(source, destination)
                    print("Edit at {}".format(destination))
                counter +=1
                key_name = esml_step_types.IN_2_SILVER + "_" + str(counter)
                self._script_names_dic[key_name] = destination
            
            # SILVER_MERGED_2_GOLD
            source = self._script_template_enterprise + "/" + self._silver2gold_filename
            gold_to_score = self._snapshot_folder + self._silver2gold_filename
            if(not only_info):
                shutil.copy(source, gold_to_score)
                print("Edit at {}".format(gold_to_score))
            self._script_names_dic[esml_step_types.SILVER_MERGED_2_GOLD] = gold_to_score

            # SCORE_GOLD
            source = self._script_template_enterprise + "/" + self._scoring_filename
            scoring_gold = self._snapshot_folder + self._scoring_filename
            if(not only_info):
                shutil.copy(source, scoring_gold)
                print("Edit at {}".format(scoring_gold))
            self._script_names_dic[esml_step_types.SCORING_GOLD] = scoring_gold

             # your_custom_code.PY
            init_py_name = "your_custom_code.py"
            source = self._script_template_enterprise + "/" + init_py_name
            initpy = self._snapshot_folder + "your_code/"+ init_py_name
            if(not only_info):
                os.makedirs(os.path.dirname(self._snapshot_folder + "your_code/"), exist_ok=True)
                shutil.copy(source, initpy)
                print("Edit at {}".format(initpy))
            self._script_names_dic["Custom code"] = initpy

            # __INIT__.PY
            init_py_name = "__init__.py"
            source = self._script_template_enterprise + "/" + init_py_name
            initpy = self._snapshot_folder + init_py_name
            if(not only_info):
                shutil.copy(source, initpy)
        finally:
            os.chdir(old_loc)
        return self._script_names_dic

    def create_batch_pipeline(self, pipeline_type=esml_pipeline_types.IN_2_GOLD_SCORING, same_compute_for_all=True, cpu_gpu_databricks="cpu", allow_reuse=True):
        p = self.p
        self._allow_reuse = allow_reuse
        # 2) Load DEV or TEST or PROD Azure ML Studio workspace
        p.ws = p.get_workspace_from_config()
        p.inference_mode = True
        self._datalake = p.connect_to_lake()  # Get Lake

        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            self._create_scriptfolder_and_download_files()
        finally:
            os.chdir(old_loc)

        pipe = None
        if(pipeline_type == esml_pipeline_types.IN_2_GOLD_SCORING):
            pipe = self._create_pipeline(same_compute_for_all,cpu_gpu_databricks)
        else: # TODO: Switch/Case on  esml_pipeline_types, to support multiple types
            raise ValueError('ESML does not support this pipeline type, as of this moment. Check for updates..')
            
        return pipe
# endregion

#region(collapsed) PRIVATE - init
    from azureml.core.model import Model
    def _create_scriptfolder_and_download_files(self):
        os.makedirs(self._snapshot_folder, exist_ok=True)

        # NOTE: Below commented is STALE if you switch lake_settings without a training run to refresh "run_id"
        '''
        inference_config_to_override_and_inject, model, best_run = self.p.get_active_model_inference_config() 
        inference_env = best_run.get_environment()
        best_run.download_file(
            # Download model.pkl for SNAPSHOT
            "outputs/model.pkl", os.path.join(
                self._snapshot_folder, "model.pkl")
        )
        '''
        model = self.p.get_best_model_via_experiment_name() # This is not stale
        m = model.download(target_dir=self.get_snapshot_dir_relative(), exist_ok=True)
        return m

    def _create_parameters(self):
        self._batch_pipeline_parameters.clear()
        par_esml_model_version = PipelineParameter(name="esml_inference_model_version", default_value=self.p.inferenceModelVersion)
        par_esml_scoring_date = PipelineParameter(name="esml_scoring_folder_date", default_value=str(self.p.date_scoring_folder))
        par_esml_guid_folder = PipelineParameter(name="esml_optional_unique_scoring_folder", default_value="*")
        
        # PIPELINE  "locked and loaded" in a TEST workspace, but needed for LAKE folder
        par_esml_environment = PipelineParameter(name="esml_environment_dev_test_prod", default_value=self.p.dev_test_prod)
        
        # self._batch_pipeline_parameters.append(par_esml_model_version,par_esml_scoring_date,par_esml_environment,par_esml_guid_folder)
        self._batch_pipeline_parameters += [par_esml_model_version,
                                            par_esml_scoring_date,
                                            par_esml_guid_folder,
                                            par_esml_environment]

#endregion

#region(collapsed) PRIVATE - BATCH PIPELINE -----------------------------------------------------------
    def _create_pipeline(self, same_compute_for_all = True, aml_compute=None):
        p = self.p
        step_array = []

        compute = None
        runconfig = None
        for d in p.Datasets:
            if(same_compute_for_all and compute is not None):
                pass # we alreday wave compute and runconfig
            else:
                if (d.runconfig is None):  # Create default RunConfig, based on ESML settings
                    if(d.cpu_gpu_databricks == "cpu"):
                        compute, runconfig = self.init_cpu_environment()
                    elif(d.cpu_gpu_databricks == "databricks"):
                        compute, runconfig = self.init_databricks_environment()
                    elif(d.cpu_gpu_databricks == "gpu"):
                        compute, runconfig = self.init_gpu_environment()
                else:  # User user configured RunConfig and compute. Custom
                    runconfig = d.runconfig  # Each dataset can have different compute or environment
                    compute = d.runconfig.target
            
            # 1) Silver datasets (multiple)
            step_array.append(self.create_esml_step(d, compute,runconfig,esml_step_types.IN_2_SILVER)) 

        # 2) Gold to score (merge all silver datasets)
        gold_to_score = self.create_gold_to_score_step(compute,runconfig,step_array)
        step_array.append(gold_to_score)
        
        # 3) Score Gold (Do the actual scoring, and saves result to LAKE)
        step_array.append(self.create_score_gold_step(compute,runconfig,gold_to_score))
        pipeline = Pipeline(workspace = p.ws, steps=step_array)

        return pipeline

    def get_silver_as_inputs(self,silver_steps):
        silver_input_array = []
        silver_names = []
        for step in silver_steps:
            out_ds = step._outputs[0] # Get output of step
            name = out_ds.name
            out_as_input = out_ds.as_input(name) # Convert as input
            silver_names.append(name)
            silver_input_array.append(out_as_input)
        return silver_input_array,silver_names

    def create_score_gold_step(self,compute, runconfig, gold_to_score_step):
        p = self.p
        # IN: Gold to score
        latest_scored_folder = p.path_gold_scored_template().format(model_version=0) # 0= latest scored
        latest_gold_scored_path = latest_scored_folder + "{run-id}"
        scored_folder_template = p.path_gold_scored_template(True,True)
        gold_to_score = gold_to_score_step._outputs[0] # gives us the "OutputFileDatasetConfig"

        # OUT:
        scored_gold = (
            OutputFileDatasetConfig(name= p.dataset_gold_scored_name_azure,destination=(self._datalake,latest_gold_scored_path))
            .as_upload(overwrite=True) # as_mount() also works
            .read_parquet_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            .register_on_complete(name= p.dataset_gold_scored_name_azure)
        )

        last_gold_run = (
            OutputFileDatasetConfig(name=p.dataset_gold_scored_runinfo_name_azure,destination=(self._datalake,p.path_inference_gold_scored_runinfo))
            .as_upload(overwrite=True) # as_mount() also works
            .read_delimited_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            .register_on_complete(name=p.dataset_gold_scored_runinfo_name_azure)
        )

        active_folder = (
            OutputFileDatasetConfig(name=p.dataset_active_name_azure,destination=(self._datalake, p.path_inference_active))
            .as_upload(overwrite=True) # as_mount() also works
            #.read_delimited_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            #.register_on_complete(name=p.dataset_active_name_azure)
        )

        step_score_gold = PythonScriptStep(
            runconfig=runconfig,
            script_name=self._scoring_filename,
            name="SCORING GOLD",
            arguments=[
            "--target_column_name",self._target_column_name,
            "--par_esml_model_version",self.batch_pipeline_parameters[0],
            "--par_esml_scoring_date",self.batch_pipeline_parameters[1],
            "--esml_output_lake_template",scored_folder_template,
            "--par_esml_env", self.batch_pipeline_parameters[3] # optional
            ],
            inputs=[gold_to_score.as_input(gold_to_score.name)], 
            outputs=[scored_gold,last_gold_run,active_folder], 
            source_directory=self.get_snapshot_dir_relative(),
            compute_target=compute,
            allow_reuse=self._allow_reuse
        )

        return step_score_gold

    def create_gold_to_score_step(self,compute, runconfig, silver_steps):
        p = self.p

        # INPUT - All silver outputs as input
        silver_input_array,silver_names = self.get_silver_as_inputs(silver_steps)

        # OUT: gold_to_score_folder = gold_to_score_path+'{run-id}'
        path_gold_to_score_template_latest = p.path_gold_to_score_template()
        path_gold_to_score_template_pars = p.path_gold_to_score_template(True,True)
        gold_to_score_folder = path_gold_to_score_template_latest.format(model_version = 0) # 0 means "latest" par_esml_model_version.default_value
        gold_to_score_name = p.dataset_gold_to_score_name_azure

        gold_to_score = (
            OutputFileDatasetConfig(name=gold_to_score_name,destination=(self._datalake,gold_to_score_folder))
            .as_upload(overwrite=True) # as_mount() also works
            .read_parquet_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            .register_on_complete(name=gold_to_score_name)
        )

        step_gold_merged = PythonScriptStep(
            runconfig=runconfig,
            script_name=self._silver2gold_filename,
            name=esml_step_types.SILVER_MERGED_2_GOLD.replace("_"," "),
            arguments=[
            "--azure_dataset_names"," ".join(silver_names),
            #"--azure_dataset_names",silver_names, # Not nessesary, depending on how to fetch datasets
            "--target_column_name",self._target_column_name,
            "--par_esml_model_version",self.batch_pipeline_parameters[0],
            "--par_esml_scoring_date",self.batch_pipeline_parameters[1],
            "--esml_output_lake_template",path_gold_to_score_template_pars,
            "--par_esml_env", self.batch_pipeline_parameters[3], # optional - good for logging purpose
            "--esml_optional_unique_scoring_folder", self.batch_pipeline_parameters[2] # optional parameter
            ],
            inputs=silver_input_array,
            outputs=[gold_to_score],
            source_directory=self.get_snapshot_dir_relative(),
            compute_target=compute,
            allow_reuse=self._allow_reuse
        )

        return step_gold_merged

    def create_esml_step(self, d, compute, runconfig, step_type=esml_step_types.IN_2_SILVER):
        
        # IN Dataset: Can be .csv or .parquet
        in_template, in_name, input_path, out_name, out_path, script_name_template,ds_IN = self.set_step_vars(d, step_type)
        #print("Scoring IN full path, template: {}".format(input_path))

        # OUT Dataset always .parquet
        path = out_path + "{run-id}/"
        ds_OUT = (
            OutputFileDatasetConfig(
                name=out_name,
                destination=(self._datalake, path))  # partition_format='/{PipelineUniqueRunId}/silver.parquet'
            .as_upload(overwrite=True)
            .read_parquet_files()
            .register_on_complete(name=out_name)
        )

        step = PythonScriptStep(
            runconfig=runconfig,
            script_name=script_name_template,
            name=step_type.replace("_"," ") + " - "+ d.Name,
            arguments=["--esml_input_lake_template", in_template,
                    "--par_esml_model_version", self.batch_pipeline_parameters[0], 
                    "--par_esml_scoring_date", self.batch_pipeline_parameters[1],
                    "--esml_optional_unique_scoring_folder", self.batch_pipeline_parameters[2],  # optional
                    "--par_esml_env", self.batch_pipeline_parameters[3] # does not need to be a parameter that changes runtime
                    ],
            inputs=[ds_IN.as_named_input(in_name)],
            outputs=[ds_OUT],  # optional, adds to
            source_directory=self.get_snapshot_dir_relative(),
            compute_target=compute,
            allow_reuse=self._allow_reuse
        )
        return step  # step._outputs[0] gives us "ds_OUT_SILVER"

    def set_step_vars(self, d, step_type):
        if (step_type == esml_step_types.IN_2_SILVER):
            in_template =  d.InPathTemplate
            in_name = d.AzureName_IN
            in_path = self.create_template_path(in_template)
            ds_IN = None
            try: # TODO: Add dummy data,since bug that validate=False does not work, still gives DatasetValidationError 
                input_path = in_path + "*.csv"
                ds_IN = Dataset.Tabular.from_delimited_files(path = [(self._datalake, input_path)], validate=False)
            except:
                input_path = in_path + "*.parquet"
                ds_IN = Dataset.Tabular.from_parquet_files(path = [(self._datalake, input_path)], validate=False)

            out_name = d.AzureName_Silver
            out_path = d.SilverPath
            script_name_template = d.in2silver_filename
        elif(step_type == esml_step_types.BRONZE_2_SILVER):
            in_template =  d.BronzePathTemplate
            in_name = d.AzureName_Bronze
            in_path = in_template.format(
                    inference_model_version=self.batch_pipeline_parameters[0].default_value,
                    dev_test_prod=self.batch_pipeline_parameters[3].default_value)
            input_path = in_path + "*.parquet"
            ds_IN = Dataset.Tabular.from_parquet_files(path = [(self._datalake, input_path)], validate=False)

            out_name = d.AzureName_Silver
            out_path = d.SilverPath
            script_name_template = d.bronze2silver_filename
        elif(step_type == esml_step_types.IN_2_BRONZE):
            in_template =  d.InPathTemplate
            in_name = d.AzureName_IN
            in_path = self.create_template_path(in_template)
            ds_IN = None
            try: # TODO: Add dummy data,since bug that validate=False does not work, still gives DatasetValidationError 
                input_path = in_path + "*.csv"
                ds_IN = Dataset.Tabular.from_delimited_files(path = [(self._datalake, input_path)], validate=False)
            except:
                input_path = in_path + "*.parquet"
                ds_IN = Dataset.Tabular.from_parquet_files(path = [(self._datalake, input_path)], validate=False)

            out_name = d.AzureName_Bronze
            out_path = d.AzureName_Bronze
            script_name_template = d.in2bronze_filename
        
        return in_template,in_name,input_path,out_name,out_path,script_name_template,ds_IN

    def create_template_path(self,in_template_path):
        date_infolder = datetime.datetime.strptime(self.batch_pipeline_parameters[1].default_value, '%Y-%m-%d %H:%M:%S.%f')
        scoring_date_dummy = date_infolder.strftime('%Y/%m/%d') #  String 2020/01/01
        
        # IN "a template" - path will be reset dynamically during runtime.
        path = in_template_path.format(
            inference_model_version=self.batch_pipeline_parameters[0].default_value,
            dev_test_prod=self.batch_pipeline_parameters[3].default_value,
            scoring_folder_date=scoring_date_dummy)
        return path

    def get_snapshot_dir_relative(self):
        old_loc = os.getcwd()
        script_dir = None
        try:
            os.chdir(os.path.dirname(__file__))
            script_dir = os.path.realpath(self._snapshot_folder)
        finally:
            os.chdir(old_loc)
        return script_dir
#endregion

#region PRIVATE environments
    def init_databricks_environment(self):
        pass

    def init_gpu_environment(self):
        pass

    def init_cpu_environment(self, use_curated_automl_env=True, conda_dependencies_object=None):
        # Get compute, for active environment.
        aml_compute = self.p.get_training_aml_compute(self.p.ws)
        aml_run_config = RunConfiguration()
        # `compute_target` as defined in "Azure Machine Learning compute" section above
        aml_run_config.target = aml_compute

        USE_CURATED_ENV = use_curated_automl_env
        if USE_CURATED_ENV:
            # "AzureML-Tutorial" https://docs.microsoft.com/en-us/azure/machine-learning/resource-curated-environments
            curated_environment = Environment.get(
                workspace=self.p.ws, name="AzureML-AutoML")
            aml_run_config.environment = curated_environment
        else:
            aml_run_config.environment.python.user_managed_dependencies = False

            if (conda_dependencies_object is None):  # Add some packages relied on by data prep step
                aml_run_config.environment.python.conda_dependencies = CondaDependencies.create(
                    conda_packages=['pandas==0.25.1',
                                    'scikit-learn==0.22.1', 'numpy==1.18.5', ''],
                    pip_packages=['azureml-defaults',
                                  'azureml-dataprep[fuse,pandas]'],  # azureml-sdk
                    pin_sdk_version=False)

                # Alt 2 ) Create an Environment for the experiment
                #batch_process_env = Environment.from_conda_specification("esml_batch_prep_environment_v02", script_folder + "/esml_batch_environment.yml")
                # batch_process_env.docker.base_image = DEFAULT_CPU_IMAGE # mcr.microsoft.com/mlops/python:latest
            else:
                aml_run_config.environment.python.conda_dependencies = conda_dependencies_object

            docker_config = DockerConfiguration(use_docker=True)
            aml_run_config.docker = docker_config
        return aml_compute, aml_run_config

#endregion

#region TRAIN pipeline
    def create_training_pipe(self):
        pass

#endregion

#region PUBLIC - Util
    def describe(self):
        date_infolder = datetime.datetime.strptime(self.batch_pipeline_parameters[1].default_value, '%Y-%m-%d %H:%M:%S.%f')
        scoring_date_dummy = date_infolder.strftime('%Y/%m/%d') #  String 2020/01/01

        
        script_dictionary = self.print_script_files()
        print("")
        print(" ---- Q: WHICH files are generated as templates, for you to EDIT? ---- ")
        print("A: These files & locations:")
        for k in script_dictionary.keys():
            #print("Step: {}".format(k))
            if (k == "Custom code"):
                print("File to EDIT a lot (reference in step-scripts {}): {}".format(k,script_dictionary[k]))
            else:
                print("File to EDIT (step: {}): {}".format(k,script_dictionary[k]))
        print("")

        print(" ---- WHAT model to SCORE with, & WHAT data 'date_folder'? ---- ")
        #print("InferenceModelVersion (model version to score with): {}".format(self.p.inferenceModelVersion))
        print("InferenceModelVersion (model version to score with): {}".format(self._batch_pipeline_parameters[0].default_value))
        #print("Date_scoring_folder (data to score) : {}".format(str(self.p.date_scoring_folder)))
        print("Date_scoring_folder (data to score) : {}".format(self._batch_pipeline_parameters[1].default_value))
        print("ESML environment:", self.p.dev_test_prod)
        print("")

        print(" ---- ESML Datalake locations: ESML Datasets (IN-data) ---- ")
        
        for d in self.p.Datasets:
            print("Name (lake folder): {} and AzureName IN: {}".format(d.Name,d.AzureName_IN))
            
            print("IN", d.InPath)
            print("Bronze", d.BronzePath)
            print("Silver", d.SilverPath)
            print("")
            #print("Full IN path")
            #input_path = d.InPathTemplate.format(
            #    inference_model_version=self.batch_pipeline_parameters[0].default_value,
            #    dev_test_prod=self.batch_pipeline_parameters[2].default_value,
            #    scoring_folder_date=scoring_date_dummy)
            #print(input_path)

    def get_automl_run(self, pipeline_run, experiment):
        # workaround to get the automl run as its the last step in the pipeline,  get_steps() returns the steps from latest to first
        for step in pipeline_run.get_steps():
            automl_step_run_id = step.id
            print(step.name)
            print(automl_step_run_id)
            break  # latest step found
        automl_run = AutoMLRun(experiment=experiment,
                               run_id=automl_step_run_id)

#endregion

#region(collapsed) DOCS - relevant

  # STATIC - functions to download output to local and fetch as dataframe
  # https://github.com/Azure/MachineLearningNotebooks/blob/master/how-to-use-azureml/machine-learning-pipelines/nyc-taxi-data-regression-model-building/nyc-taxi-data-regression-model-building.ipynb
#endregion

#region(collapsed) EJ KLART

 # TODO: Trigger/Schedules: https://docs.microsoft.com/en-us/azure/machine-learning/how-to-trigger-published-pipeline
    '''
    from azureml.pipeline.core import PublishedPipeline
    published_pipelines = PublishedPipeline.list(p.ws)
    for pub_pipe in published_pipelines:
    print(pub_pipe.name)
    '''
    def publish_pipeline_from_latestrun_with_version_if_exists(self):
        p = self.p
        # Get "Pipelin run" info, for tghe most recent "latest scored gold"
        ds1 = Dataset.get_by_name(workspace = self.p.ws, name =  p.dataset_gold_scored_runinfo_name_azure)
        run_id = ds1.to_pandas_dataframe().iloc[0]["pipeline_run_id"] # ['pipeline_run_id', 'scored_gold_path', 'date_in_parameter', 'date_at_pipeline_run','model_version'])
        experiment = Experiment(workspace=p.ws, name=p.experiment_name)
        remote_run = PipelineRun(experiment=experiment, run_id=run_id)

        new_pipeline = None # remote_run.pipeline
        existing_pipeline_endpoint = None
        found_pipeline = None
        pipeline_name = self.name_batch_pipeline
        endpoint_name = self.name_batch_pipeline + "_Endpoint"
        exists = False
        
        published_pipelines = PublishedPipeline.list(p.ws)
        for pub_pipe in published_pipelines:
            print ("pub_pipe.name", pub_pipe.name)
            print ("pub_pipe.id", pub_pipe.id)
            if(pub_pipe.name == pipeline_name):
                found_pipeline = pub_pipe
                exists = True
                break

        if (exists):
            print("Exists!")
            print("Type: {}", str(type(found_pipeline)))
            print("Name: {}", found_pipeline.name)
            #existing_pipeline_endpoint = PipelineEndpoint.get(workspace=p.ws, name=endpoint_name)
            #existing_pipeline_endpoint.add_default(new_pipeline) # Add new version
        else:
            print("Create NEW pipeline, and publish 1st version")
            # Create NEW pipeline
            #published_pipeline1 = remote_run.publish_pipeline(
            #name=self.name_batch_pipeline,
            #description=self.description_batch_pipeline,
            #version="1.0")

            # Publish the NEW pipeline (for it to exist next time)
            #published_id = published_pipeline1.id
            #published_pipeline = PublishedPipeline.get(workspace=p.ws, id=published_id) # unexpected keyword argument 'name'
            #pipeline_endpoint = PipelineEndpoint.publish(workspace=p.ws, name=endpoint_name,
            #                                pipeline=published_pipeline, description=self.description_batch_pipeline)

#endregion