#region(collapsed) IMPORTS
from genericpath import exists
import os
import datetime
import shutil
from azureml.core import Experiment
from azureml.core import Model
from azureml.data.constants import NONE
from azureml.telemetry import UserErrorException
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
from azureml.core import Run
from azureml.train.automl import AutoMLConfig

from azureml.pipeline.steps import AutoMLStep
from azureml.pipeline.steps import AutoMLStepRun
from azureml.pipeline.core import TrainingOutput, PipelineData
from azureml.core import Datastore

#endregion
#region(collapsed) Enumerators
class esml_pipeline_types():
    IN_2_GOLD_SCORING = "IN_2_GOLD_SCORING"
    IN_2_GOLD = "IN_2_GOLD"
    GOLD_SCORING = "GOLD_SCORING"
    IN_2_GOLD_TRAIN_AUTOML= "IN_2_GOLD_TRAIN_AUTOML"
    IN_2_GOLD_TRAIN_MANUAL= "IN_2_GOLD_TRAIN_MANUAL"
    #BRONZE_2_GOLD = "BRONZE_2_GOLD"
    #BRONZE_2_GOLD_SCORING = "BRONZE_2_GOLD_SCORING"

class esml_step_types():
    IN_2_BRONZE = "IN_2_BRONZE"
    BRONZE_2_SILVER = "BRONZE_2_SILVER"
    IN_2_SILVER = "IN_2_SILVER"
    SILVER_MERGED_2_GOLD = "SILVER_MERGED_2_GOLD"
    SCORING_GOLD = "SCORING_GOLD"
    TRAIN_AUTOML = "TRAIN_AUTOML"
    TRAIN_MANUAL = "TRAIN_MANUAL"
    TRAIN_SPLIT_AND_REGISTER = "TRAIN_SPLIT_AND_REGISTER"

#endregion

# ESMLPipelineFactory brings same logging for ALL models in enterprise. Uniform way of pipelines
class ESMLPipelineFactory():
    p = None
    _use_curated_automl_environment = True
    # https://docs.microsoft.com/en-us/azure/machine-learning/resource-curated-environments
    _environment_name = "AzureML-AutoML-DNN" # # Training[ "AzureML-AutoML","AzureML-AutoML-DNN", "AzureML-lightgbm-3.2-ubuntu18.04-py37-cpu"]  Inference["AzureML-sklearn-0.24.1-ubuntu18.04-py37-cpu-inference",]
    _use_own_compute_per_step = False
    _pipeline_steps_array = []
    _datalake = None
    _allow_reuse = True
    _batch_pipeline_parameters = []
    _target_column_name = None
    _esml_pipeline_type = None
    _script_names_dic = {}
    _script_template_enterprise = "../../../settings/enterprise_specific/dev_test_prod_defaults/batch/pipeline_template"
    _script_template_enterprise_runtime = "../../esmlrt"
    _script_template_project_settings = "../../../settings/project_specific/model"

    #region(collapsed) TODO
    #script_template_user = "../../../settings/project_specific/model/dev_test_prod_override/batch/pipeline_template"
    #endregion
    _snapshot_folder = "../../../2_A_aml_pipeline/4_inference/batch/"

#region USER CUSTOMIZATION - EDIT the code in THESE files. Init files with "create_dataset_scripts_from_template()"
    _in2silver_filename = "in2silver.py"
    _silver2gold_filename = "silver_merged_2_gold.py"
    _scoring_filename = "scoring_gold.py"
    _train_split_and_register_file = "train_split_and_register.py"
    _train_manual_filename = "train_manual.py"
    _train_automl_filename = "train_post_automl_step.py"

    _in2bronze_filename = "in2bronze.py" # Not used in In2Silver2Gold data model
    _bronze2silver_filename = "bronze2silver.py" # Not used In2Silver2Gold data model

#endregion

# region(collapsed) INIT
    def __init__(self, project, target_column_name = None, esml_pipeline_type = esml_pipeline_types.IN_2_GOLD_SCORING):
        self.p = project
        if(target_column_name is None):
            self._target_column_name = project.active_model["label"]
        else:
            self._target_column_name = target_column_name
        self._esml_pipeline_type = esml_pipeline_type
        self._snapshot_folder = self._snapshot_folder + self.p.ModelAlias+ "/" # self.p.model_folder_name
        self._create_parameters()
# endregion

#region PUBLIC Properties

    # ENVIRONMENT vs CONDA
    @property
    def environment_name(self):
        return self._environment_name
    
    @environment_name.setter
    def environment_name(self, environment_name):
        self._environment_name = environment_name

    @property
    def use_curated_automl_environment(self):
        return self._use_curated_automl_environment
    
    @use_curated_automl_environment.setter
    def use_curated_automl_environment(self, use_curated_automl_environment):
        self._use_curated_automl_environment = use_curated_automl_environment

    # STEPS
    @property
    def pipeline_steps_array(self):
        return self._pipeline_steps_array
    
    @pipeline_steps_array.setter
    def pipeline_steps_array(self, pipeline_steps_array):
        self._pipeline_steps_array = pipeline_steps_array

    # COMPUTE
    @property
    def use_own_compute_per_step(self):
        return self._use_own_compute_per_step
    
    #@use_own_compute_per_step.setter
    #def use_own_compute_per_step(self, use_own_compute_per_step):
    #    self._use_own_compute_per_step = use_own_compute_per_step

    # PIPELINE PARAMETERS
    @property
    def batch_pipeline_parameters(self):
        return self._batch_pipeline_parameters

    # PIPELINE - Name, endpoint, description etc
    @property
    def name_batch_pipeline(self):

        if(self._esml_pipeline_type ==  esml_pipeline_types.IN_2_GOLD_SCORING):
            return self.p.experiment_name + "_pipe_IN_2_GOLD_SCORING"
        elif(self._esml_pipeline_type ==  esml_pipeline_types.IN_2_GOLD):
            if(self.p.inference_mode == True):
                return self.p.experiment_name + "_pipe_IN_2_GOLD"
            else:
                return self.p.experiment_name + "_pipe_IN_2_GOLD_TRAIN" # 4_TRAIN_or_PBI
        elif(self._esml_pipeline_type ==  esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML or self._esml_pipeline_type ==  esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL):
            return self.p.experiment_name + "_pipe_IN_2_GOLD_TRAIN"
        elif(self._esml_pipeline_type ==  esml_pipeline_types.GOLD_SCORING):
            return self.p.experiment_name + "_pipe_GOLD_SCORING"
        else:
            return self.p.experiment_name + "_pipeline_OTHER"

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
            #print ("pub_pipe.name", ep.name)
            #print ("pub_pipe.id", ep.id)
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
                raise UserErrorException("Pipeline is None.You need to provide a pipeline, or update ESML to support fire and forget =  creating a pipeline on the fly of certain type")
                pipeline = self.create_batch_bronze2gold_scoring_if_not_exists()
            elif(pipeline_type == esml_pipeline_types.GOLD_SCORING):
                raise UserErrorException("Pipeline is None.You need to provide a pipeline, or update ESML to support fire and forget =  creating a pipeline on the fly of certain type")
                pipeline = self.create_batch_gold_scoring_if_not_exists()

        experiment_name = self.name_batch_pipeline
        experiment = Experiment(self.p.ws,experiment_name)
        par_dic = None
        if (pipeline_type == esml_pipeline_types.IN_2_GOLD_SCORING or pipeline_type == esml_pipeline_types.IN_2_GOLD):
            print ("Execute_pipeline (scoring): Inference_mode: {}".format(parameters[4].default_value))
            print ("-Scoring data, default value {}".format(parameters[1].default_value))

            par_dic = {
                parameters[0].name: parameters[0].default_value, # esml_inference_model_version
                parameters[1].name: parameters[1].default_value,# esml_scoring_folder_date | par_esml_training_date
                parameters[2].name: parameters[2].default_value, # esml_optional_unique_scoring_folder # par_esml_dev_test_prod
                parameters[3].name: parameters[3].default_value, # par_esml_dev_test_prod
                parameters[4].name: parameters[4].default_value # par_esml_inference_mode
            }
        elif (pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL or pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML):
            print ("Execute_pipeline (training): Inference_mode: {}".format(parameters[4].default_value))
            print ("-Training data, default value: {}".format(parameters[1].default_value))

            par_dic = {
                parameters[0].name: parameters[0].default_value, # esml_inference_model_version
                parameters[1].name: parameters[1].default_value,# esml_scoring_folder_date | par_esml_training_date
                parameters[2].name: parameters[2].default_value, # esml_optional_unique_scoring_folder # par_esml_dev_test_prod
                parameters[3].name: parameters[3].default_value, # par_esml_dev_test_prod
                parameters[4].name: parameters[4].default_value, # par_esml_inference_mode
                parameters[5].name: parameters[5].default_value # par_esml_split_percentage
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
        print(" ### ")
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
                file_exist = os.path.exists(gold_test_if_exists)
                if(not overwrite_if_exists and file_exist):
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

             # TRAIN_SPLIT_AND_REGISTER
            source = self._script_template_enterprise + "/" + self._train_split_and_register_file
            train_split = self._snapshot_folder + self._train_split_and_register_file
            if(not only_info):
                shutil.copy(source, train_split)
                print("Edit at {}".format(train_split))
            self._script_names_dic[esml_step_types.TRAIN_SPLIT_AND_REGISTER] = train_split

            # TRAIN_MANUAL
            source = self._script_template_enterprise + "/" + self._train_manual_filename
            train_manual = self._snapshot_folder + self._train_manual_filename
            if(not only_info):
                shutil.copy(source, train_manual)
                print("Edit at {}".format(train_manual))
            self._script_names_dic[esml_step_types.TRAIN_MANUAL] = train_manual

            # TRAIN_AUTOML
            source = self._script_template_enterprise + "/" + self._train_automl_filename
            train_automl = self._snapshot_folder + self._train_automl_filename
            if(not only_info):
                shutil.copy(source, train_automl)
                print("Edit at {}".format(train_automl))
            self._script_names_dic[esml_step_types.TRAIN_AUTOML] = train_automl

             # your_custom_code.PY
            init_py_name = "your_custom_code.py"
            source = self._script_template_enterprise + "/your_code/" + init_py_name
            initpy = self._snapshot_folder + "your_code/"+ init_py_name
            if(not only_info):
                os.makedirs(os.path.dirname(self._snapshot_folder + "your_code/"), exist_ok=True)
                shutil.copy(source, initpy)
                print("Edit at {}".format(initpy))
            self._script_names_dic["Custom code"] = initpy

            # your_train_code.PY
            source_file = "your_train_code.py"
            source = self._script_template_enterprise + "/your_code/" + source_file
            target_file = self._snapshot_folder + "your_code/" + source_file
            if(not only_info):
                shutil.copy(source, target_file)

            # __INIT__.PY
            init_py_name = "__init__.py"
            source = self._script_template_enterprise + "/" + init_py_name
            initpy = self._snapshot_folder + init_py_name
            if(not only_info):
                shutil.copy(source, initpy)

            # RUNTIME
            source = self._script_template_enterprise_runtime
            target = self._snapshot_folder + "esmlrt"
            if(not only_info):
                shutil.copytree(source, target,dirs_exist_ok=True)
            
            # SETTINGS
            
            project_settings = 'model_settings.json'
            source = self._script_template_project_settings + "/" + project_settings
            target_folder = self._snapshot_folder + "esmlrt/settings/project_specific/model/"
            
            target_file = target_folder + project_settings
            if(not only_info):
                os.makedirs(os.path.dirname(target_folder), exist_ok=True)
                shutil.copy(source, target_file)
                
        finally:
            os.chdir(old_loc)
        return self._script_names_dic

    def create_batch_pipeline(self, pipeline_type=esml_pipeline_types.IN_2_GOLD_SCORING, same_compute_for_all=True, cpu_gpu_databricks="cpu", allow_reuse=True):
        p = self.p
        self._esml_pipeline_type = pipeline_type
        if(pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL or pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML):
            p.inference_mode = False
        else:
            p.inference_mode = True


        self._allow_reuse = allow_reuse
        # 2) Load DEV or TEST or PROD Azure ML Studio workspace
        p.ws = p.get_workspace_from_config()
        #p.inference_mode = True
        self._datalake = p.connect_to_lake(False)  # Get Lake, but don't use "date_folder from lake", use contstructor

        old_loc = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__))
            model = self._create_scriptfolder_and_download_files(pipeline_type)
        finally:
            os.chdir(old_loc)
        
        try: 
            esml_current_mode = p.inference_mode
            pipe = None
            if(pipeline_type == esml_pipeline_types.IN_2_GOLD_SCORING):
                p.inference_mode = True
                pipe = self._create_pipeline(pipeline_type,same_compute_for_all,cpu_gpu_databricks)
            elif(pipeline_type == esml_pipeline_types.IN_2_GOLD):
                p.inference_mode = True
                pipe = self._create_pipeline(pipeline_type,same_compute_for_all,cpu_gpu_databricks)
            elif(pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL):
                p.inference_mode = False
                pipe = self._create_pipeline(pipeline_type,same_compute_for_all,cpu_gpu_databricks)
            elif(pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML):
                p.inference_mode = False
                pipe = self._create_pipeline(pipeline_type,same_compute_for_all,cpu_gpu_databricks)
            else: # TODO: Switch/Case on  esml_pipeline_types, to support multiple types
                raise ValueError('ESML does not support this pipeline type, as of this moment. Check for updates..')
        finally:
            p.inference_mode = esml_current_mode
            
        return pipe
# endregion

#region(collapsed) PRIVATE - init
    from azureml.core.model import Model

    def getBestModel(self):
        p = self.p
        aml_model = None
        aml_model_name = None
        esml_model_name = p.model_folder_name
        source_fitted_model = None
        best_run = None

        # model = p.get_best_model_via_modeltags_only(self.p.ws,self.p.experiment_name, filter_on_version=1) # Version=1 is the TEMPLATE "LakeStructure"...hence Model=1 and not 2...since placegolder data is always model_version=1
        if(aml_model is None):
            print("Tryingt to get CURRENT leader model from Azure ML Studio workspace - remotely.This might be the first time training model. then None is returned \n")

            try:
                # 0 - Get "Pipelin run" info, for the most recent "trained model"
                ds1 = Dataset.get_by_name(workspace = self.p.ws, name =  p.dataset_gold_train_runinfo_name_azure)
                run_id = ds1.to_pandas_dataframe().iloc[0]["pipeline_run_id"] #  ['pipeline_run_id', 'training_data_used', 'training_data_source_date', 'date_at_pipeline_run','model_version_current','model_version_newly_trained']
                experiment = Experiment(workspace=p.ws, name=p.experiment_name)
                
                #remote_run = AutoMLRun(experiment=experiment, run_id=run_id)

                # 1
                try:
                    remote_run = PipelineRun(experiment=experiment, run_id=run_id)
                    best_run, source_fitted_model = remote_run.get_output()
                except Exception as e:
                    #print("1)Soft Error: PipelineRun .get_output() gave error {}".format(e))
                    #print("2)Soft Error: Now trying as AutoMLRun instead of PipelineRun, to get Run() and fitted_model")
                    try:
                        remote_run = AutoMLRun(experiment=experiment, run_id=run_id)
                        best_run, source_fitted_model = remote_run.get_output()
                    except:
                        print("It was not an AutoMLRun() Lets init it as a regular Run()")
                        remote_run = Run(experiment=experiment, run_id=run_id)
                        best_run = remote_run # , source_fitted_model = remote_run.get_output()


                # 2
                aml_model_name = best_run.properties['model_name']
                aml_model = Model(self.ws, aml_model_name)
            except:
                pass

        return aml_model,aml_model_name, source_fitted_model, esml_model_name

    def _create_scriptfolder_and_download_files(self,pipeline_type):
        os.makedirs(self._snapshot_folder, exist_ok=True)
        m = None

        if(pipeline_type != esml_pipeline_types.IN_2_GOLD): # Don't fetch model If we only want to REFINE data
            #model = self.p.get_best_model_via_experiment_name(self.p.ws) 
            model = self.p.get_best_model_via_modeltags_only(self.p.ws,self.p.experiment_name, filter_on_version=1) # Version=1 is the TEMPLATE "LakeStructure"...hence Model=1 and not 2...since placegolder data is always model_version=1
            #self._batch_pipeline_parameters[0].default_value = model.version # If we are in DEV and have registered Model in TEST - seting default_value to LATEST model version (2,3,4), requires placeholder Data in Lake for VERSION
            #print("Model version (get_best_model_via_modeltags_only): {}".format(model.version))

            if(model is None):
                print("Could not fetch BEST MODEL from Azure ML Studo - remotely.This might be the first time training model. \n - Now trying with local cache model.")
                model =  self.p.BestModel
            m = model.download(target_dir=self.get_snapshot_dir_relative(), exist_ok=True)
        return m

    def _create_parameters(self):
        self._batch_pipeline_parameters.clear()
        par_esml_model_version = PipelineParameter(name="esml_inference_model_version", default_value=self.p.inferenceModelVersion)
        par_esml_split_percentage = PipelineParameter(name="esml_split_percentage", default_value=0.6)

        if(self.p.inference_mode):
            par_esml_scoring_date = PipelineParameter(name="esml_scoring_folder_date", default_value=str(self.p.date_scoring_folder))
        else:
            par_esml_scoring_date = PipelineParameter(name="esml_training_folder_date", default_value=str(self.p.date_scoring_folder))

        par_esml_guid_folder = PipelineParameter(name="esml_optional_unique_scoring_folder", default_value="*")
        
        # PIPELINE  "locked and loaded" in a TEST workspace, but needed for LAKE folder
        par_esml_environment = PipelineParameter(name="esml_environment_dev_test_prod", default_value=self.p.dev_test_prod)
        
        # IN_2_GOLD is used for both TRAIN and INFERENCE
        inference_mode_as_int = int(self.p.inference_mode) # True == 1
        par_esml_inference_mode = PipelineParameter(name="esml_inference_mode", default_value=inference_mode_as_int)
        
        # self._batch_pipeline_parameters.append(par_esml_model_version,par_esml_scoring_date,par_esml_environment,par_esml_guid_folder)
        self._batch_pipeline_parameters += [par_esml_model_version,
                                            par_esml_scoring_date,
                                            par_esml_guid_folder,
                                            par_esml_environment,
                                            par_esml_inference_mode,
                                            par_esml_split_percentage]

#endregion

#region(collapsed) PRIVATE - BATCH PIPELINE -----------------------------------------------------------
    def _create_pipeline(self, pipeline_type = esml_pipeline_types.IN_2_GOLD_SCORING, same_compute_for_all = True, aml_compute=None):
        p = self.p
        step_array = []

        compute = None
        runconfig = None
        old_mode = p.inference_mode
        try:
            if(pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL or pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML): # TRAINING
                self.p.inference_mode = False
                par_esml_inference_mode = PipelineParameter(name="esml_inference_mode", default_value=0)
                self.batch_pipeline_parameters[4] = par_esml_inference_mode
            else:
                self.p.inference_mode = True
                par_esml_inference_mode = PipelineParameter(name="esml_inference_mode", default_value=1)
                self.batch_pipeline_parameters[4] = par_esml_inference_mode

            if(pipeline_type == esml_pipeline_types.IN_2_GOLD_SCORING or 
                pipeline_type == esml_pipeline_types.IN_2_GOLD or 
                pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL or
                pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML):

                compute_suffix = 1

                for d in p.Datasets:
                    if(same_compute_for_all and compute is not None):
                        print("Reusing existing compute...")
                        pass # we alreday have compute and runconfig
                    elif(same_compute_for_all and compute is None):
                        print("ESML will auto-create a compute...")
                        if (d.runconfig is None):  # Create default RunConfig, based on ESML settings
                            if(d.cpu_gpu_databricks == "cpu"):
                                compute, runconfig = self.init_cpu_environment(self._use_curated_automl_environment)
                            elif(d.cpu_gpu_databricks == "databricks"):
                                compute, runconfig = self.init_databricks_environment(self._use_curated_automl_environment)
                            elif(d.cpu_gpu_databricks == "gpu"):
                                compute, runconfig = self.init_gpu_environment(self._use_curated_automl_environment)
                        else:  # User user configured RunConfig and compute. Custom
                            runconfig = d.runconfig  # Each dataset can have different compute or environment
                            compute = d.runconfig.target
                    elif(same_compute_for_all == False):
                        print("ESML will create separate compute, per SILVER-step to run in parallell...")
                        compute_suffix_str = str(compute_suffix)

                        if (d.runconfig is None):  # Create default RunConfig, based on ESML settings
                            if(d.cpu_gpu_databricks == "cpu"):
                                compute, runconfig = self.init_cpu_environment(self._use_curated_automl_environment,compute_suffix_str)
                            elif(d.cpu_gpu_databricks == "databricks"):
                                compute, runconfig = self.init_databricks_environment(self._use_curated_automl_environment,compute_suffix_str)
                            elif(d.cpu_gpu_databricks == "gpu"):
                                compute, runconfig = self.init_gpu_environment(self._use_curated_automl_environment,compute_suffix_str)
                        else:  # User user configured RunConfig and compute. Custom
                            runconfig = d.runconfig  # Each dataset can have different compute or environment
                            compute = d.runconfig.target

                        compute_suffix = compute_suffix+1

                    # 1) Silver datasets (multiple)
                    step_array.append(self.create_esml_step(d, compute,runconfig,esml_step_types.IN_2_SILVER)) 

            gold_to_score= None
            if(pipeline_type == esml_pipeline_types.IN_2_GOLD_SCORING or 
                pipeline_type == esml_pipeline_types.IN_2_GOLD or 
                pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL or 
                pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML):
                # 2) Gold to score (merge all silver datasets)
                gold_to_score = self.create_gold_to_score_step(compute,runconfig,step_array)
                step_array.append(gold_to_score)
            
            if(pipeline_type == esml_pipeline_types.IN_2_GOLD_SCORING or pipeline_type == esml_pipeline_types.GOLD_SCORING): # SCORING
                if(pipeline_type == esml_pipeline_types.IN_2_GOLD_SCORING):
                    step_array.append(self.create_score_gold_step(compute,runconfig,gold_to_score))
                elif(pipeline_type == esml_pipeline_types.GOLD_SCORING):
                    raise NotImplementedError("Not suppported in your ESML version. Please ask admin for private preview, or run IN_2_GOLD_SCORING instead of only GOLD_SCORING")
                    path_gold_to_score_template_latest = p.path_gold_to_score_template()
                    path_gold_to_score_template_pars = p.path_gold_to_score_template(True,True)
                    gold_to_score_folder = path_gold_to_score_template_latest.format(model_version = 0) # 0 means "latest" par_esml_model_version.default_value
                    gold_to_score_name = p.dataset_gold_to_score_name_azure
                    step_array.append(self.create_score_gold_step(compute,runconfig,gold_to_score))
            
            if(pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL or pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML): # TRAINING
                split_gold = self.create_split_gold_step(compute,runconfig,gold_to_score)
                step_array.append(split_gold)

                if (pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_MANUAL):
                    step_array.append(self.create_train_gold_step_manual(compute,runconfig,split_gold))
                elif(pipeline_type == esml_pipeline_types.IN_2_GOLD_TRAIN_AUTOML):
                    train_automl_step,model_data,metrics_data = self.create_train_automl_step(compute,runconfig,split_gold)
                    step_array.append(train_automl_step)
                    step_array.append(self.create_post_AutoMLStep(compute,runconfig,split_gold,train_automl_step,model_data,metrics_data))
                    #raise NotImplementedError("Not suppported in your ESML version, try 'IN_2_GOLD_TRAIN_MANUAL' instead . Please ask admin for private preview for IN_2_GOLD_TRAIN_AUTOML, or use ESML IN_2_GOLD_TRAIN_AUTOML Agentless.")
                    
            self._pipeline_steps_array = step_array
            pipeline = Pipeline(workspace = p.ws, steps=step_array)
        finally: 
             self.p.inference_mode = old_mode
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

    def create_split_gold_step(self,compute, runconfig, gold_to_split_step):
        p = self.p
        
        # IN: Gold to score
        if(type(gold_to_split_step) is OutputFileDatasetConfig):  # esml_pipeline_type.SCORE_GOLD 
            gold_to_split = gold_to_split_step # gives us the "OutputFileDatasetConfig"
        else: # esml_pipeline_type.IN_2_GOLD_SCORING
            gold_to_split = gold_to_split_step._outputs[0] # gives us the "OutputFileDatasetConfig"

        # OUT: Splitted datasets

        #train_path = p.GoldPath + 'Train/1_latest/' # projects/project002/10_titanic_model_clas/train/gold/dev/Train/1_latest/
        #validate_path = p.GoldPath + 'Validate/1_latest/' # projects/project002/10_titanic_model_clas/train/gold/{env}/Validate/{guid}/*.parquet
        #test_path = p.GoldPath + 'Test/1_latest/'


        train_path,validate_path,test_path = p.path_gold_train_splitted_template() # projects/project002/11_diabetes_model_reg/train/gold/dev/Train/{id_folder}}/
        train_path_out = train_path.format(id_folder="{run-id}")
        validate_path_out = validate_path.format(id_folder="{run-id}")
        test_path_out = test_path.format(id_folder="{run-id}")
        
        print("ESML-train_path_out = ".format(train_path_out))

        #train_path = train_path + '*.parquet' # projects/project002/11_diabetes_model_reg/train/gold/dev/Train/8e9792b1f7e84d40b3dd29dbc5a91a37/*.parquet
        #validate_path = validate_path + '*.parquet'
        #test_path = test_path + '*.parquet'

        #train_version_folder = train_path + uuid.uuid4().hex + "/"

        train_ds = (
            OutputFileDatasetConfig(name=p.dataset_gold_train_name_azure,destination=(self._datalake,train_path_out))
            .as_upload(overwrite=True) # as_mount() also works
            .read_parquet_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            .register_on_complete(name=p.dataset_gold_train_name_azure)
        )
        validate_ds = (
            OutputFileDatasetConfig(name=p.dataset_gold_validate_name_azure,destination=(self._datalake,validate_path_out))
            .as_upload(overwrite=True) # as_mount() also works
            .read_parquet_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            .register_on_complete(name=p.dataset_gold_validate_name_azure)
        )
        test_ds = (
            OutputFileDatasetConfig(name=p.dataset_gold_test_name_azure,destination=(self._datalake,test_path_out))
            .as_upload(overwrite=True) # as_mount() also works
            .read_parquet_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            .register_on_complete(name=p.dataset_gold_test_name_azure)
        )

        #name_auto = esml_step_types.TRAIN_SPLIT_AND_REGISTER.replace("_"," ")
        name_w_split_per = "SPLIT AND REGISTER ("+str(self.batch_pipeline_parameters[5].default_value)+" % TRAIN)"

        step_split_gold = PythonScriptStep(
            runconfig=runconfig,
            script_name=self._train_split_and_register_file,
            name="SPLIT AND REGISTER datasets",
            arguments=[
            "--target_column_name",self._target_column_name,
            "--par_esml_split_percentage",self.batch_pipeline_parameters[5], # 0.6 as default for TRAIN
            "--par_esml_training_date",self.batch_pipeline_parameters[1], # datefolder with TRAIN data
            "--par_esml_env", self.batch_pipeline_parameters[3], # not needed, since static
            "--par_esml_inference_mode", self.batch_pipeline_parameters[4], # does not need to be a parameter that changes runtime...but at DEFINITION time.
            "--esml_output_lake_template_train",train_path,
            "--esml_output_lake_template_validate",validate_path,
            "--esml_output_lake_template_test",test_path
            ],
            inputs=[gold_to_split.as_input(gold_to_split.name)], 
            outputs=[train_ds,validate_ds,test_ds], 
            source_directory=self.get_snapshot_dir_relative(),
            compute_target=compute,
            allow_reuse=self._allow_reuse
        )

        return step_split_gold

    def create_train_gold_step_manual(self,compute, runconfig, gold_to_split_step):
        p = self.p

        # Get model name info, and current model info
        aml_model,aml_model_name, current_fitted_model, esml_model_name = self.getBestModel()

        # projects/project002/11_diabetes_model_reg/train/gold/dev/{todays_date_folder}/{run-id}/
        train_folder_template_with_date_and_run_id = p.path_gold_scored_template(date_folder=False,id_folder=True, inference_mode = False)
        print("train_folder_template_with_date_id: {}".format(train_folder_template_with_date_and_run_id))

        train_out = None
        validate_out = None
        test_out = None

        if(type(gold_to_split_step) is OutputFileDatasetConfig):  # esml_pipeline_type.SCORE_GOLD 
            train_out = gold_to_split_step # gives us the "OutputFileDatasetConfig"
        else: # esml_pipeline_type.IN_2_GOLD_SCORING
            train_out = gold_to_split_step._outputs[0] # gives us the "OutputFileDatasetConfig"
            validate_out = gold_to_split_step._outputs[1]
            test_out = gold_to_split_step._outputs[2]

        # OUT: Training meta data (scoring, promote=True, etc)
        last_gold_training_run = (
            OutputFileDatasetConfig(name=p.dataset_gold_train_runinfo_name_azure,destination=(self._datalake,p.path_gold_trained_runinfo))
            .as_upload(overwrite=True) # as_mount() also works
            .read_delimited_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            .register_on_complete(name=p.dataset_gold_train_runinfo_name_azure)
        )

        #name_incl_env = "TRAINING in ESML " + self.batch_pipeline_parameters[3] +" performance"
        name_auto = esml_step_types.TRAIN_MANUAL.replace("_"," ")
        name_incl_env = name_auto + " ["+self.batch_pipeline_parameters[3].default_value +"]"
        name_incl_env = "TRAIN in "+ " ["+self.batch_pipeline_parameters[3].default_value +"]" +", COMPARE & REGISTER model in " + "["+self.batch_pipeline_parameters[3].default_value +"] & PROMOTE to [test]"

        step_train_gold = PythonScriptStep(
            runconfig=runconfig,
            script_name=self._train_manual_filename,
            name=name_incl_env,
            arguments=[
            "--target_column_name",self._target_column_name,
            "--par_esml_model_version",self.batch_pipeline_parameters[0], # model to compare with (inner loop), version=0 if first time
            "--par_esml_training_date",self.batch_pipeline_parameters[1], # training data
            "--esml_train_lake_template",train_folder_template_with_date_and_run_id,
            "--par_esml_env", self.batch_pipeline_parameters[3], # not needed, since static
            "--par_esml_inference_mode", self.batch_pipeline_parameters[4], # does not need to be a parameter that changes runtime...but at DEFINITION time.
            "--par_esml_model_alias", p.ModelAlias,
            "--par_esml_model_name", p.model_folder_name,
            "--par_aml_model_name", aml_model_name
            ],
            inputs=[train_out.as_input(train_out.name),validate_out.as_input(validate_out.name),test_out.as_input(test_out.name)], 
            outputs=[last_gold_training_run], 
            source_directory=self.get_snapshot_dir_relative(),
            compute_target=compute,
            allow_reuse=self._allow_reuse
        )

        return step_train_gold

    def create_post_AutoMLStep(self,compute, runconfig, gold_to_split_step, train_automl_step,model_data,metrics_data):
        p = self.p

        # Get model name info, and current model info
        aml_model,aml_model_name, current_fitted_model, esml_model_name = self.getBestModel()

        # projects/project002/11_diabetes_model_reg/train/gold/dev/{todays_date_folder}/{run-id}/
        train_folder_template_with_date_and_run_id = p.path_gold_scored_template(date_folder=False,id_folder=True, inference_mode = False)
        print("train_folder_template_with_date_id: {}".format(train_folder_template_with_date_and_run_id))

        train_out = None
        validate_out = None
        test_out = None

        if(type(gold_to_split_step) is OutputFileDatasetConfig):  # esml_pipeline_type.SCORE_GOLD 
            train_out = gold_to_split_step # gives us the "OutputFileDatasetConfig"
        else: # esml_pipeline_type.IN_2_GOLD_SCORING
            train_out = gold_to_split_step._outputs[0] # gives us the "OutputFileDatasetConfig"
            validate_out = gold_to_split_step._outputs[1]
            test_out = gold_to_split_step._outputs[2]

        # OUT: Training meta data (scoring, promote=True, etc)
        last_gold_training_run = (
            OutputFileDatasetConfig(name=p.dataset_gold_train_runinfo_name_azure,destination=(self._datalake,p.path_gold_trained_runinfo))
            .as_upload(overwrite=True) # as_mount() also works
            .read_delimited_files()  # To promote File to Tabular Dataset. This, or .read_delimited_files()  will return/converts to an "OutputTabularDatasetConfig"
            .register_on_complete(name=p.dataset_gold_train_runinfo_name_azure)
        )

        name_incl_env = "["+self.batch_pipeline_parameters[3].default_value +"]" +"Calculate SCORING on TEST_SET, COMPARE & REGISTER model in " + "["+self.batch_pipeline_parameters[3].default_value +"] & PROMOTE to [test]"

        step_train_gold = PythonScriptStep(
            runconfig=runconfig,
            script_name=self._train_automl_filename,
            name=name_incl_env,
            arguments=[
            "--target_column_name",self._target_column_name,
            "--par_esml_model_version",self.batch_pipeline_parameters[0], # model to compare with (inner loop), version=0 if first time
            "--par_esml_training_date",self.batch_pipeline_parameters[1], # training data
            "--esml_train_lake_template",train_folder_template_with_date_and_run_id,
            "--par_esml_env", self.batch_pipeline_parameters[3], # not needed, since static
            "--par_esml_inference_mode", self.batch_pipeline_parameters[4], # does not need to be a parameter that changes runtime...but at DEFINITION time.
            "--par_esml_model_alias", p.ModelAlias,
            "--par_esml_model_name", p.model_folder_name,
            "--par_aml_model_name", aml_model_name,
            "--model_name", p.model_folder_name,
            "--model_path", model_data
            ],
            inputs=[test_out.as_input(test_out.name),model_data], 
            outputs=[last_gold_training_run], 
            source_directory=self.get_snapshot_dir_relative(),
            compute_target=compute,
            allow_reuse=self._allow_reuse
        )

        return step_train_gold

    #
    # You must set enable_default_model_output and enable_default_metrics_output to True only if you are using AutoMLStepRun.
    #
    def create_train_automl_step(self,compute, runconfig, gold_to_split_step):
        p = self.p

        label = p.active_model["label"]
        automl_performance_config = p.get_automl_performance_config() # 1)Get config, for active environment (dev,test or prod)
        #aml_compute = p.get_training_aml_compute(p.ws) # 2)Get compute, for active environment

        train_out = gold_to_split_step._outputs[0] # gives us the "OutputFileDatasetConfig"
        validate_out = gold_to_split_step._outputs[1]
        test_out = gold_to_split_step._outputs[2]

        automl_config = AutoMLConfig(task = 'regression',  #TODO: move as a parameter in get_automl_performance_config()
                            primary_metric = 'normalized_mean_absolute_error', #TODO: move as a parameter in get_automl_performance_config()
                            compute_target = compute,
                            #run_configuration = runconfig,
                            training_data = train_out, # p.GoldTrain, 
                            experiment_exit_score = '0.308', # DEMO purpose #TODO: pass as a parameter "DEMO"
                            label_column_name = label,
                            **automl_performance_config
                        )

        # Save model information
        # https://docs.microsoft.com/en-us/azure/machine-learning/v1/how-to-use-automlstep-in-pipelines
        datastore = Datastore(p.ws, 'workspaceblobstore')
        metrics_data = PipelineData(name='metrics_data',
                            datastore=datastore,
                            pipeline_output_name='metrics_output',
                            training_output=TrainingOutput(type='Metrics'))

        model_data = PipelineData(name='best_model_data',
                          datastore=datastore,
                          pipeline_output_name='model_output',
                          training_output=TrainingOutput(type='Model'))

        name_auto = esml_step_types.TRAIN_MANUAL.replace("_"," ")
        name_incl_env = name_auto + " ["+self.batch_pipeline_parameters[3].default_value +"]"
        name_incl_env = "AutoML TRAIN in "+ " ["+self.batch_pipeline_parameters[3].default_value +"]"
        
        train_step = AutoMLStep(name=name_incl_env,
            automl_config=automl_config,
            passthru_automl_config=False,
            outputs=[metrics_data,model_data], # NB! PipelineData use DataReference underlying which is no longer the recommended approach for data access and delivery, please use OutputFileDatasetConfig instead
            enable_default_model_output=False, # You must set enable_default_model_output and enable_default_metrics_output to True only if you are using AutoMLStepRun.
            enable_default_metrics_output=False,
            allow_reuse=self._allow_reuse)

        return train_step,model_data,metrics_data

    def create_score_gold_step(self,compute, runconfig, gold_to_score_step):
        p = self.p
        # IN: Gold to score
        latest_scored_folder = p.path_gold_scored_template().format(model_version=0) # 0= latest scored
        latest_gold_scored_path = latest_scored_folder + "{run-id}"
        scored_folder_template = p.path_gold_scored_template(True,True)

        if(type(gold_to_score_step) is OutputFileDatasetConfig):  # esml_pipeline_type.SCORE_GOLD 
            gold_to_score = gold_to_score_step # gives us the "OutputFileDatasetConfig"
        else: # esml_pipeline_type.IN_2_GOLD_SCORING
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
            "--par_esml_env", self.batch_pipeline_parameters[3], # not needed, since static
            "--par_esml_inference_mode", self.batch_pipeline_parameters[4] # does not need to be a parameter that changes runtime...but at DEFINITION time.
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
        next_step_is_databricks_step = False # TODO: Figure this via "runconfig.target = amlcompute or databricks"

        # INPUT - All silver outputs as input
        silver_input_array,silver_names = self.get_silver_as_inputs(silver_steps)

        # OUT: gold_to_score_folder = gold_to_score_path+'{run-id}'
        gold_to_score_folder = ""
        gold_to_score_name = ""
        path_gold_to_score_template_pars = ""

        if(p.inference_mode == True):
            print("create_gold_to_score_step: inference_mode=True")
            path_gold_to_score_template_latest = p.path_gold_to_score_template()
            gold_to_score_folder = path_gold_to_score_template_latest.format(model_version = 0) # 0 means "latest" par_esml_model_version.default_value

            path_gold_to_score_template_pars = p.path_gold_to_score_template(True,True)
            gold_to_score_name = p.dataset_gold_to_score_name_azure # dataset_gold_name_azure
        else:
            print("create_gold_train_step: inference_mode=False")
            path_gold_to_score_template_pars = p.path_gold_to_score_template(False,True,False) # projects/project002/11_diabetes_model_reg/train/gold/dev/{id_folder}/
            gold_to_score_name = p.dataset_gold_name_azure
            gold_to_score_folder = p.path_gold_to_score_template(False,False,False)
            if(next_step_is_databricks_step):
                gold_to_score_folder = gold_to_score_folder + "gold_dbx.parquet"
            else: 
                gold_to_score_folder = gold_to_score_folder + "1_latest/"


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
            "--par_esml_inference_mode", self.batch_pipeline_parameters[4], #
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
                    "--par_esml_env", self.batch_pipeline_parameters[3], # does not need to be a parameter that changes runtime
                    "--par_esml_inference_mode", self.batch_pipeline_parameters[4] # does not need to be a parameter that changes runtime...but at DEFINITION time.
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
        if(self.p.inference_mode == True):
            path = in_template_path.format(
                inference_model_version=self.batch_pipeline_parameters[0].default_value,
                dev_test_prod=self.batch_pipeline_parameters[3].default_value,
                folder_date=scoring_date_dummy)
        else:
            path = in_template_path.format(dev_test_prod=self.batch_pipeline_parameters[3].default_value,folder_date=scoring_date_dummy)
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

    def init_cpu_environment(self, use_curated_automl_env=True, conda_dependencies_object=None, suffix_char=None):

        if(suffix_char is None):
            aml_compute = self.p.get_training_aml_compute(self.p.ws) # Create or Get compute, for active environment.
        else:
            aml_compute = self.p.get_training_aml_compute(self.p.ws, False,suffix_char) # Create or Get compute, for active environment.
        aml_run_config = RunConfiguration()
        # `compute_target` as defined in "Azure Machine Learning compute" section above
        aml_run_config.target = aml_compute

        USE_CURATED_ENV = use_curated_automl_env
        if USE_CURATED_ENV:
            # "AzureML-Tutorial" https://docs.microsoft.com/en-us/azure/machine-learning/resource-curated-environments
            #curated_environment = Environment.get(workspace=self.p.ws, name="AzureML-AutoML")
            curated_automl = self.environment_name # "AzureML-AutoML"
            #curated_sklearn ="AzureML-sklearn-0.24.1-ubuntu18.04-py37-cpu-inference"
            curated_environment = Environment.get(workspace=self.p.ws, name=curated_automl)

            aml_run_config.environment = curated_environment
        else:
            aml_run_config.environment.python.user_managed_dependencies = False

            if (conda_dependencies_object is None):  # Add some packages relied on by data prep step
                #aml_run_config.environment.python.conda_dependencies = CondaDependencies.create(
                    #conda_packages=['pandas==0.25.1','scikit-learn==0.22.1', 'numpy==1.18.5', ''],
                    #pip_packages=['azureml-defaults','azureml-dataprep[fuse,pandas]'],  # azureml-sdk
                    #pin_sdk_version=False)
                
                # Specify CondaDependencies obj, add necessary packages
                aml_run_config.environment.python.conda_dependencies = CondaDependencies.create(
                    conda_packages=['pandas','scikit-learn'],
                    pip_packages=['azureml-sdk[automl]', 'pyarrow'])

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
        print("Inference mode (self.batch_pipeline_parameters[4]): {}".format(self._batch_pipeline_parameters[4].default_value))
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