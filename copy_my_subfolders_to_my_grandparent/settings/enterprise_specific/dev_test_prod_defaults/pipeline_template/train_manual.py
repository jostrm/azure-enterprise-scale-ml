import os
import pandas as pd
import argparse
from azureml.core import Run
from azureml.data.dataset_factory import FileDatasetFactory
import datetime
from esmlrt.interfaces.iESMLController import IESMLController
from esmlrt.interfaces.iESMLModelCompare import IESMLModelCompare
from esmlrt.interfaces.iESMLTestScoringFactory import IESMLTestScoringFactory
from esmlrt.interfaces.iESMLTrainer import IESMLTrainer

from esmlrt.runtime.ESMLController import ESMLController
from esmlrt.runtime.ESMLModelCompare2 import ESMLModelCompare
from esmlrt.runtime.ESMLTestScoringFactory2 import ESMLTestScoringFactory
from your_code.your_train_code import Trainer
from azureml.core import Dataset
import joblib

def init():
    global prev_model,train_ds,validate_ds,test_ds, last_gold_training_run,datastore,historic_path,run,run_id,active_folder,date_in,model_version_in,esml_env,esml_model_alias,esml_modelname,aml_model_name,target_column_name,ws
    global project_number,ml_type,secret_name_tenant,secret_name_sp_id,secret_name_sp_secret
    global dev_resourcegroup_id,dev_workspace_name,dev_subscription_id,test_resourcegroup_id,test_workspace_name,test_subscription_id,prod_resourcegroup_id,prod_workspace_name,prod_subscription_id

    parser = argparse.ArgumentParser("Split the GOLD and Train the model")
    parser.add_argument('--target_column_name', dest="target_column_name", type=str, required=True)
    parser.add_argument('--par_esml_training_date', dest="par_esml_training_date", required=True)
    parser.add_argument('--par_esml_model_version', dest="par_esml_model_version", required=True)
    parser.add_argument('--esml_train_lake_template', dest="esml_train_lake_template", required=True)
    parser.add_argument('--par_esml_inference_mode', dest='par_esml_inference_mode', type=int, required=True)
    
    parser.add_argument('--par_esml_model_alias', dest='par_esml_model_alias', type=str, required=True)
    parser.add_argument('--par_esml_model_name', dest='par_esml_model_name', type=str, required=True)
    parser.add_argument('--par_aml_model_name', dest='par_aml_model_name', type=str, required=False)
    parser.add_argument('--par_esml_env', type=str, help='ESML environment: dev,test,prod', required=True)

    parser.add_argument('--project_number', dest='project_number', type=str, required=True)
    parser.add_argument('--ml_type', dest='ml_type', type=str, required=True)
    parser.add_argument('--secret_name_tenant', dest='secret_name_tenant', type=str, required=True)
    parser.add_argument('--secret_name_sp_id', dest='secret_name_sp_id', type=str, required=True)
    parser.add_argument('--secret_name_sp_secret', dest='secret_name_sp_secret', type=str, required=True)

    # envs
    parser.add_argument('--dev_resourcegroup_id', dest='dev_resourcegroup_id', type=str, required=True)
    parser.add_argument('--dev_workspace_name', dest='dev_workspace_name', type=str, required=True)
    parser.add_argument('--dev_subscription_id', dest='dev_subscription_id', type=str, required=True)

    parser.add_argument('--test_resourcegroup_id', dest='test_resourcegroup_id', type=str, required=True)
    parser.add_argument('--test_workspace_name', dest='test_workspace_name', type=str, required=True)
    parser.add_argument('--test_subscription_id', dest='test_subscription_id', type=str, required=True)

    parser.add_argument('--prod_resourcegroup_id', dest='prod_resourcegroup_id', type=str, required=True)
    parser.add_argument('--prod_workspace_name', dest='prod_workspace_name', type=str, required=True)
    parser.add_argument('--prod_subscription_id', dest='prod_subscription_id', type=str, required=True)

    # optional
    parser.add_argument('--previous_step_is_databricks', dest='previous_step_is_databricks',help='Flag=1 if previous step is a DatabriksStep',required=False, type=int)
    parser.add_argument('--esml_gold_train_databricks_path', dest='esml_gold_train_databricks_path',help='Path to Databricks GOLD TRAIN',required=False, type=str)
    parser.add_argument('--esml_gold_validate_databricks_path', dest='esml_gold_validate_databricks_path',help='Path to Databricks GOLD VALIDATE',required=False, type=str)
    parser.add_argument('--esml_gold_test_databricks_path', dest='esml_gold_test_databricks_path',help='Path to Databricks GOLD TRAIN TEST',required=False, type=str)
       
    
    args = parser.parse_args()
    print("init() started - train manual...")

    try:
        model_version_in = int(args.par_esml_model_version) # Model version to compare scoring with (MLOps INNER LOOOP)
        esml_inference_mode = bool(args.par_esml_inference_mode) # Verify, should be False
        esml_env = args.par_esml_env
        # model info
        esml_model_alias = args.par_esml_model_alias
        esml_modelname = args.par_esml_model_name
        aml_model_name = args.par_aml_model_name
        target_column_name = args.target_column_name

        #project info & security
        project_number = args.project_number
        ml_type = args.ml_type

        secret_name_tenant = args.secret_name_tenant
        secret_name_sp_id = args.secret_name_sp_id
        secret_name_sp_secret = args.secret_name_sp_secret

        #envs
        dev_subscription_id = args.dev_subscription_id
        test_subscription_id = args.test_subscription_id
        prod_subscription_id = args.prod_subscription_id

        dev_resourcegroup_id = args.dev_resourcegroup_id
        test_resourcegroup_id = args.test_resourcegroup_id
        prod_resourcegroup_id = args.prod_resourcegroup_id

        dev_workspace_name = args.dev_workspace_name
        test_workspace_name = args.test_workspace_name
        prod_workspace_name = args.prod_workspace_name

        if_user_implmeneted_model_compare = False
        if(if_user_implmeneted_model_compare):
            print("Loading model version {} from path: model.pkl to compare the future trained model with (version 0 if first time)".format(model_version_in))
            try:
                # ###############  Custom code below - Load model. Tip: Look at how ESML loads model with AutoML automatically
                #prev_model = joblib.load("model.pkl")
                print("Loading previous registered (current winning model) - success - model.pkl")
                # ###############  Custom code below -  Load model
            except:
                pass

        run = Run.get_context()
        ws = run.experiment.workspace
        datastore = ws.get_default_datastore()

        # INPUT:
        it1 = iter(run.input_datasets.items())
        train_ds = next(it1)[1] 
        validate_ds = next(it1)[1] # Get 2nd DATASET: GOLD_VALIDATE
        test_ds = next(it1)[1] # Get 3rd DATASET: GOLD_TEST

        print("Azure ML Dataset Train, Validate, Test loaded successfully. {}, {}, {}".format(train_ds.name,validate_ds.name,test_ds.name))
        print("Azure ML Dataset Tran is of TYPE: {}".format(type(train_ds)))

        try:
            train_ds2 = Dataset.get_by_name(workspace=ws, name=train_ds,  version='latest')
            print("train_ds2.Azure ML Dataset  is of TYPE: {}".format(type(train_ds2)))
            print("train_ds2.tags = {}".format(train_ds2.tags))
        except: 
            pass
        
        # OUTPUT: PATHS
        # 1) Save META data: "WHAT data was used, when did the training occur in time, etc "  (train_gold path, run_id, pipeline_id )
        it = iter(run.output_datasets)
        last_gold_training_run_name =next(it) # Get 1st key in dictionary
        last_gold_training_run = run.output_datasets[last_gold_training_run_name]

        # 2) Save TRAINING in lake also (besides in Azure ML as experiment), with parameter in real time: DATE_FOLDER, MODEL_VERSION from calling applicatiom (Data factory)
        date_in = args.par_esml_training_date
        date_infolder = datetime.datetime.strptime(date_in, '%Y-%m-%d %H:%M:%S.%f') # UTC string to DateTime object
        esml_training_day_date_out = date_infolder.strftime('%Y/%m/%d')
        run_id = run.parent.id #run.id
        #historic_path = args.esml_train_lake_template.format(date_folder = esml_training_day_date_out,id_folder= run_id)
        # Example: projects/project002/11_diabetes_model_reg/train/gold/dev/Train/{"2020/01/01"}/{"8e9792b1f7e84d40b3dd29dbc5a91a37"}/
        historic_path = args.esml_train_lake_template.format(id_folder=run_id)
        # Example: projects/project002/11_diabetes_model_reg/train/gold/dev/Train/{8e9792b1f7e84d40b3dd29dbc5a91a37}/
        

        print("train_gold.py.init() success: Fetched INPUT and OUTPUT datasets - now lets TRAIN in the train() method")

    except Exception as e:
        raise

def train(train_ds,validate_ds,test_ds):
    try:
        print("train() started...")
        test_scoring = None # IESMLTestScoringFactory
        comparer = None # IESMLModelCompare
        #trainer = None # IESMLTrainer

        # Optional CUSTOMIZATION ############### Optional: You can CUSTOMIZE, by implementing your own CLASS that supports interfaces/abstract classes: IESMLTestScoringFactory,IESMLModelCompare
        test_scoring = ESMLTestScoringFactory(ml_type) # Optional: IF , you want to have a customized way of calculating Test_set scoring need to implement your own IESMLTestScoringFactory
        comparer = ESMLModelCompare(setting_path = "") # Optional: IF, you want to have a customized way, You need to implement IESMLModelCompare

        # Note: You can get this info in ESML by p.get_all_envs() (where p is ESMLProject)
        all_envs ={'dev': {'subscription_id': dev_subscription_id,'resourcegroup_id': dev_resourcegroup_id,'workspace_name': dev_workspace_name},
        'test': {'subscription_id': test_subscription_id,'resourcegroup_id': test_resourcegroup_id,'workspace_name': test_workspace_name},
        'prod': {'subscription_id': prod_subscription_id,'resourcegroup_id': prod_resourcegroup_id,'workspace_name': prod_workspace_name}}

        # Optional CUSTOMIZE END ###############
        controller = ESMLController(comparer,test_scoring,project_number,esml_modelname, esml_model_alias,all_envs, secret_name_tenant,secret_name_sp_id,secret_name_sp_secret) # IESMLController: you do not have to change/implemen this class. Dependency injects default or your class.

        model_registered_in_target = train_test_compare_register(controller,ws,target_column_name,esml_modelname,esml_model_alias, esml_env, train_ds,validate_ds,test_ds,ml_type)
        return model_registered_in_target
    except Exception as e:
        raise

def train_test_compare_register(controller,ws,target_column_name,esml_modelname,esml_model_alias, esml_current_env, train_ds,validate_ds,test_ds, ml_type):
    test_scoring = controller.ESMLTestScoringFactory # IESMLTestScoringFactory
    comparer = controller.ESMLComparer # IESMLModelCompare
    trainer = None # IESMLTrainer

    controller.dev_test_prod = esml_current_env
    global model_name
    model_name = None
    main_run = run.parent # Parent is the pipeline run, current 'run' is just the current step in pipeline.
    model_registered_in_target = None

    ##1 ) Get "current" BEST mpodel 
    current_model,run_id_tag, model_name = "","",""

    current_model,run_id_tag, model_name = IESMLController.get_best_model_via_modeltags_only_DevTestProd(ws,controller.experiment_name)
    if(current_model is None):
        print("No existing model with experiment name {}. The Model name will now be same as experiment name".format(controller.experiment_name))
        current_model = None
        run_id_tag = ""
        model_name = controller.experiment_name
    else:
        print("Current BEST model is: {} from Model registry with experiment_name-TAG {}, run_id-TAG {}  model_name-TAG {}".format(current_model.name,controller.experiment_name,run_id_tag,model_name))
        if ("esml_time_updated" in current_model.tags):
            print("esml_time_updated: {}".format(current_model.tags.get("esml_time_updated")))
        print("status_code : {}".format(current_model.tags.get("status_code")))
        print("model_name  : {}".format(current_model.tags.get("model_name")))
        print("trained_in_workspace   : {}".format(current_model.tags.get("trained_in_workspace")))

    print ("esml_modelname inparameter {} and controller.experiment_name: {} and get_betModel, model_name {} ".format(esml_modelname,controller.experiment_name,model_name))

    # CUSTOMIZE ############### If using MANUAL ML you need to implement a Trainer class, that support ITrainer abstract methods/interfaces

    # ITrainer: Defaults to using AutoML. Optionally you can implement this. Else you need to implement ITrainer in 'YourTrainer' class
    trainer = Trainer(model_name,esml_modelname,esml_model_alias, esml_current_env, ml_type,train_ds,validate_ds,test_ds)
    train_run, aml_model,fitted_model,full_local_path,new_model_scoring_tags = trainer.train(train_ds,validate_ds,target_column_name)

    # Set AutoML equivalent
    manual_step_run = run # Current run
    manual_step_run_id = run.id # run_id # Current run.id
    best_run = run # current run
    fitted_model_1 = fitted_model # current trained model

    # CUSTOMIZE END ###############

    # Upload Scoring script - Only needed if MAnual ML, since AutoML does this automatically TODO 4 YOU - implement this ./your_code/your_scoring_file_v_1_0_0.py
    path_scoring_file_in_snapshot_folder = './esmlrt/settings/project_specific/model/your_{}'.format(IESMLController.get_known_scoring_file_name())
    train_run.upload_file(IESMLController.get_known_scoring_file_name(), path_scoring_file_in_snapshot_folder)

    # Copy NEW LEADING model - to known model name and known location = Same thing happens IF Databricks notebooks, passing IESMLController.get_known_model_name_pkl()
    pkl_path = 'outputs/'+IESMLController.get_known_model_name_pkl()
    with open(IESMLController.get_known_model_name_pkl(), "wb") as file:
        joblib.dump(value=fitted_model, filename=pkl_path)


    ##2 ) Register NEW TRAINED model, with TAG status_code=esml_new_trained
    time_stamp = str(datetime.datetime.now())
    ml_flow_stage = IESMLController._get_flow_equivalent(IESMLController.esml_status_new)
    tags = {"esml_time_updated": time_stamp,"status_code": IESMLController.esml_status_new,"mflow_stage":ml_flow_stage, "run_id": run_id, "model_name": model_name, "trained_in_environment": esml_current_env, 
        "trained_in_workspace": ws.name, "experiment_name": controller.experiment_name, "trained_with": "ManualPython", "ml_type":ml_type, "experiment_pipleline_run_name":run.experiment.name}

    # CLEAR scoring & Add potentially new manually calculated TEST_SET SCORING from tags
    if("test_set_ROC_AUC" in new_model_scoring_tags):
        tags["test_set_Accuracy"] = new_model_scoring_tags.get("test_set_Accuracy")
        tags["test_set_ROC_AUC"] = new_model_scoring_tags.get("test_set_ROC_AUC")
        tags["test_set_Precision"] = new_model_scoring_tags.get("test_set_Precision")
        tags["test_set_Recall"] = new_model_scoring_tags.get("test_set_Recall")
        tags["test_set_F1_Score"] = new_model_scoring_tags.get("test_set_F1_Score")
        tags["test_set_Matthews_Correlation"] = new_model_scoring_tags.get("test_set_Matthews_Correlation")
        tags["test_set_CM"] = new_model_scoring_tags.get("test_set_CM")
    if("test_set_RMSE" in new_model_scoring_tags):
        tags["test_set_RMSE"] = new_model_scoring_tags.get("test_set_RMSE")
        tags["test_set_R2"] = new_model_scoring_tags.get("test_set_R2")
        tags["test_set_MAPE"] = new_model_scoring_tags.get("test_set_MAPE")
        tags["test_set_Spearman_Correlation"] = new_model_scoring_tags.get("test_set_Spearman_Correlation")
        tags["esml_time_updated"] = time_stamp

    ##3) Register NEW model in CURRENT env
    model = controller._register_aml_model(full_local_path=full_local_path,model_name=model_name,tags=tags,target_ws=ws,description_in=run.experiment.name)

    #4) Calculate Testset scoring on NEW model
    model, val_1, val_2, val_3,val_4,val_5,reg_plt_6, val_7,class_plt_8 = controller.ESMLTestScoringFactory.get_test_scoring_8(
        ws,
        target_column_name,
        test_ds,
        fitted_model_1,
        best_run, # run or best_run
        model)
    print("Scoring for NEW model is::")
    controller.ESMLTestScoringFactory.print_test_scoring(val_1, val_2, val_2, val_3,val_4,val_5,reg_plt_6,val_7)

    a_scoring = ""
    if (controller.ESMLTestScoringFactory.ml_type == "regression"):
        a_scoring = model.tags.get("test_set_RMSE")
        print("Verifying that at least 1 scoring exists, test_set_RMSE, in TAGS on model: {}".format(a_scoring))
    elif (controller.ESMLTestScoringFactory.ml_type == "classification"):
        a_scoring = model.tags.get("test_set_Accuracy")
        print("Verifying that at least 1 scoring exists,test_set_Accuracy, in TAGS on model: {}".format(a_scoring))

    next_environment = controller.get_next_environment()

    # Get TARGET environment
    target_ws = controller.get_target_workspace(current_environment = esml_current_env, current_ws = ws, target_environment = esml_current_env)

    ## 5) COMPARE if better
    next_environment = controller.get_next_environment()
    target_ws = controller.get_target_workspace(current_environment = esml_current_env, current_ws = ws, target_environment = esml_current_env)

    promote_new_model,source_model_name,source_run_id,source_best_run,source_model,leading_model = comparer.compare_scoring_current_vs_new_model(
        new_run_id =manual_step_run_id, # pipeline_run_id, #main_run.id,
        current_ws = ws,
        current_environment = esml_current_env,
        target_environment = esml_current_env,
        target_workspace = target_ws,
        experiment_name = controller.experiment_name,
        new_model = model) # 2023: new_model = None --> new_model = model

   ## 6) REGISTER model, if better than all else, in same environment = DEV

    print("INNER LOOP (dev->dev) - PROMOTE?")
    if (promote_new_model == True): # Better than all in DEV?! (Dev or Test,  is usually current_env) - model or current_model
        print("full_local_path: {}".format(full_local_path))
        print("pkl_path: {}".format(pkl_path))

        model_registered_in_target = controller.register_model(source_ws=ws, target_env=esml_current_env, source_model=model, run=manual_step_run,esml_status=IESMLController.esml_status_promoted_2_dev,model_path=pkl_path)
        print("Promoted model! in environment {}".format(esml_current_env))

        # Better than all in DEV, Lets check if its better than all in TEST? (or prod)
        next_environment = controller.get_next_environment() # Test, or PROD
        print("OUTER LOOP(dev-test): Now trying to compare with models in environment: {}".format(next_environment))
        try:
            promote_new_model,source_model_name,source_run_id,source_best_run,source_model,leading_model = comparer.compare_scoring_current_vs_new_model(
                new_run_id = manual_step_run_id,
                current_ws = ws,
                current_environment = esml_current_env,
                target_environment = next_environment,
                target_workspace = target_ws,
                experiment_name = controller.experiment_name,
                new_model = model_registered_in_target) # 2023: new_model = None --> new_model = model_registered_in_target

            print("OUTER LOOP (dev-test): Compared 2nd time - Outer loop: Success comparing, promote_model is: {}".format(promote_new_model))

            if (promote_new_model == True):
                print("Now registering model in TARGET environment {}".format(next_environment))
                model_registered_in_target = controller.register_model(source_ws=ws, target_env="test", source_model=model,run=None,esml_status=IESMLController.esml_status_promoted_2_test,model_path=pkl_path)
                #model_registered_in_target = controller.register_model(source_ws=ws, target_env=next_environment, source_model=model,run=None)
                print("Registered model {} with version {} in TEST".format(model_registered_in_target.name,model_registered_in_target.version))

        except Exception as e1:
            print("Error/Warning: OUTER loop. Maybe you don't have a TEST and PROD environment setup? Are you running in DEMO-mode with only DEV environment")
            print(e1)

    print("Done: INNER and OUTER loop to Test is done automatically. See human approval gate in Azure Devops staging to get TEST to PROD")
    return model_registered_in_target

def save_results(model_registered_in_target):
    try:
        last_gold_run_filename = "last_train_run.csv"
        if not (last_gold_training_run is None):
            os.makedirs(last_gold_training_run, exist_ok=True)
            print("%s created" % last_gold_training_run)
            path_last_gold_run = last_gold_training_run + "/"+last_gold_run_filename
            print("Saving last_gold_run.csv at: {}".format(path_last_gold_run))

            # create the Pandas dataframe with meta, save to .csv for "Azure datafactory WriteBack pipeline/step" to use
            date_now_str = str(datetime.datetime.now())

            model_version_new= -1
            model_name_save = model_name # global model_name

            if(model_registered_in_target is not None):
                model_version_new = model_registered_in_target.version
                model_name_save = model_registered_in_target.name

            last_gold_run_data = [[run_id, historic_path,date_in,date_now_str,model_name_save,model_version_in, model_version_new]]
            df2 = pd.DataFrame(last_gold_run_data, columns = ['pipeline_run_id', 'training_data_used', 'training_data_source_date', 'date_at_pipeline_run','model_name','model_version_current','model_version_newly_trained'])
            written_df2 = df2.to_csv(path_last_gold_run, encoding='utf-8',index=False)
            print("Pipeline ID (Steps runcontext.parent.id) {}".format(run_id))

    except Exception as e:
        raise

if __name__ == "__main__":
    init()
    model_registered_in_target = train(train_ds,validate_ds,test_ds)
    save_results(model_registered_in_target)