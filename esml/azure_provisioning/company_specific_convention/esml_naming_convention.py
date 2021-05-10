import os
import json
from collections import defaultdict
class naming_convention():

    config = None
    env_dict = None

    def __init__(self):
        self.load_configuration()

    def load_configuration(self):
        try:
            old_loc = os.getcwd()
            os.chdir(os.path.dirname(__file__))

            with open("../../../../settings/enterprise_specific/naming_convention.json") as f: 
                self.config = json.load(f)
        except Exception as e:
            raise Exception("naming_convention() - could not open naming_convention.json") from e
        finally:
            os.chdir(old_loc) # Switch back to callers "working dir"

    '''
    "rg_all_caps" : true,
    "rg_common" : "msft-{esmlcmn}-weu-{dev}-rg",
    "cmn_service_datafactory" : "adf-{esmlcmn}-weu-{dev}-001",
    "cmn_keyvault" : "kv-{esmlcmn}-weu-{dev}",
    "cmn_admin_keyvault" : "kv-{esmladm}-weu-{dev}",

    "rg_project" : "msft-esml-{prj001}-weu-{dev}-rg",

    "service_azurem_ml" : "aml-{esmlprj001}-weu-{dev}-001",
    "service_azurem_ml_keyvault" : "kv-{esmlprj001}-weu-{dev}001",
    "service_azurem_ml_storage_account" : "sa{esmlprj001}weu{dev}001",
    "service_azurem_ml_appliction_insights" : "ai-{esmlprj001}-weu-{dev}",
    "service_datafactory" : "adf-{esmlprj001}-weu-{dev}-001"
    '''
    def generate(self, print_output=True, project_no="001"):
        if(self.config is None):
            self.load_configuration()

        esmlcmn = "esmlcmn"
        prj001 = "prj001"
        esmlprj001 = "esmlprj001"
        if(project_no is not None):
            prj001 = "prj"+project_no
            esmlprj001 = "esmlprj"+project_no

        env = ["dev","test","prod"]
        self.env_dict = defaultdict(list)

        # TENANT LEVEL
        adgroup_common = self.config["adgroup_common"].replace("{esmlcmn}", "{}").replace("{esmlcmn}", "{}").format(esmlcmn)
        adgroup_project = self.config["adgroup_project"].replace("{esmlprj001}", "{}").format(esmlprj001)
        cmn_sp = self.config["cmn_sp"].replace("{esmlcmn}", "{}").format(esmlcmn)
        project_sp = self.config["project_sp"].replace("{esmlprj001}", "{}").format(esmlcmn)

        cmn_subnet = self.config["cmn_subnet"].replace("{esmlcmn}", "{}").format(esmlcmn)
        project_subnet = self.config["project_subnet"].replace("{esmlprj001}", "{}").format(esmlcmn)
        project_subnet_dbx_pub = self.config["project_subnet_dbx_pub"].replace("{esmlprj001}", "{}").format(esmlcmn)
        project_subnet_dbx_priv = self.config["project_subnet_dbx_priv"].replace("{esmlprj001}", "{}").format(esmlcmn)

        # ENV LEVEL
        for e in env:
            print ("")
            print ("Environment: ", e)

            cmn_vnet = self.config["cmn_vnet"].replace("{esmlcmn}", "{}").replace("{dev}", "{}").format(esmlcmn, e)
            rg_common = self.config["rg_common"].replace("{esmlcmn}", "{}").replace("{dev}", "{}").format(esmlcmn, e)
            cmn_storage_account = self.config["cmn_storage_account"].replace("{esmlcmn}", "{}").replace("{dev}", "{}").format(esmlcmn, e)
            cmn_service_datafactory = self.config["cmn_service_datafactory"].replace("{esmlcmn}", "{}").replace("{dev}", "{}").format(esmlcmn, e)
            cmn_keyvault = self.config["cmn_keyvault"].replace("{esmlcmn}", "{}").replace("{dev}", "{}").format(esmlcmn, e)
            cmn_admin_keyvault = self.config["cmn_admin_keyvault"].replace("{esmladm}", "{}").replace("{dev}", "{}").format(esmlcmn, e)

            rg_project = self.config["rg_project"].replace("{prj001}", "{}").replace("{dev}", "{}").format(prj001, e)

            service_azurem_ml = self.config["service_azurem_ml"].replace("{esmlprj001}", "{}").replace("{dev}", "{}").format(esmlprj001, e)
            service_azurem_ml_keyvault = self.config["service_azurem_ml_keyvault"].replace("{esmlprj001}", "{}").replace("{dev}", "{}").format(esmlprj001, e)
            service_azurem_ml_storage_account = self.config["service_azurem_ml_storage_account"].replace("{esmlprj001}", "{}").replace("{dev}", "{}").format(esmlprj001, e)
            service_azurem_ml_appliction_insights = self.config["service_azurem_ml_appliction_insights"].replace("{esmlprj001}", "{}").replace("{dev}", "{}").format(esmlprj001, e)
            #service_container_registry = self.config["service_container_registry"].replace("{esmlprj001}", "{}").replace("{dev}", "{}").format(esmlprj001, e)
            service_datafactory = self.config["service_datafactory"].replace("{esmlprj001}", "{}").replace("{dev}", "{}").format(esmlprj001, e)


            if(print_output):
                print("Azure naming convention:")
                print("")
                print("ESML COMMON:")
                print("{}".format(rg_common))
                print(" {}".format(cmn_storage_account)) # saesmlprj02aiweuprod001
                print(" {}".format(cmn_service_datafactory))
                print(" {}".format(cmn_keyvault)) # kvesmlprj02aiweuprod001
                print(" {}".format(cmn_admin_keyvault))
                print(" {}".format(cmn_vnet))
                print(" {}".format(cmn_subnet))
               
                print("")
                print("PROJECT SPECIFIC")
                print("{}".format(rg_project))
                print(" {}".format(service_azurem_ml))
                print(" {}".format(service_azurem_ml_keyvault))
                print(" {}".format(service_azurem_ml_storage_account))
                print(" {}".format(service_azurem_ml_appliction_insights)) # appiesmlprj02aiweuprod001
                #print(" {}".format(service_container_registry))  # acresmlprj02aiweuprod
                print(" {}".format(service_datafactory))
                print(" {}".format(project_subnet))
                print(" {}".format(project_subnet_dbx_pub))
                print(" {}".format(project_subnet_dbx_priv))

                #esml-project005-sp
                #esml-project005-sp-id
                #esml-esmlprj005-sp-secret

            self.env_dict.setdefault(e, []).append(rg_common)
            self.env_dict.setdefault(e, []).append(cmn_service_datafactory)
            self.env_dict.setdefault(e, []).append(cmn_keyvault)
            self.env_dict.setdefault(e, []).append(cmn_admin_keyvault)
            self.env_dict.setdefault(e, []).append(cmn_vnet)
            self.env_dict.setdefault(e, []).append(cmn_subnet)

            self.env_dict.setdefault(e, []).append(rg_common)
            self.env_dict.setdefault(e, []).append(service_azurem_ml)
            self.env_dict.setdefault(e, []).append(service_azurem_ml_keyvault)
            self.env_dict.setdefault(e, []).append(service_azurem_ml_storage_account)
            self.env_dict.setdefault(e, []).append(service_azurem_ml_appliction_insights)
            self.env_dict.setdefault(e, []).append(service_datafactory)

            self.env_dict.setdefault(e, []).append(project_subnet)
            self.env_dict.setdefault(e, []).append(project_subnet_dbx_pub)
            self.env_dict.setdefault(e, []).append(project_subnet_dbx_priv)                        


        if(print_output): # TENANT LEVEL
            print("")
            print("TENANT level - AuthN/AuthZ ############## used for ALL environments(dev,test,prod)")
            print("")
            print("COMMON")
            print(" AD group=", adgroup_common)
            print(" Service principle=", cmn_sp)
            print("")
            print("PROJECT SPECIFIC")
            print(" AD group=",adgroup_project)
            print(" Service principle=",project_sp)

            print("")
            # esml-common-sp
            # esml-common-sp-id
            # esml-common-sp-secret

            #esml-project005-sp
            #esml-project005-sp-id
            #esml-esmlprj005-sp-secret
            
            
            print ("TENANT level - END")

            print("")
            print("PE: Private Endpoint example names:")
            print(" - mlcmn - ")
            print("esmlcmn-lake-storage-blob-to-vnt-cmn-pe")
            print("esmlcmn-lake-storage-dfs-to-vnt-cmn-pe")
            print("esmlcmn-lake-storage-file-to-vnt-cmn-pe")
            print("esmlcmn-adm-keyvault-to-vnt-cmn-pe")
            print(" - project - ")
            print("esmlprj001-aml-to-vnt-cmn-pe") # esmlprj002-aml-to-vnt-cmn-prod-pe
            print("esmlproj001-aml-acr-to-vnt-cmn-pe")
            print("esmlproj001-aml-keyvault-to-vnt-cmn-pe")
            print("esmlproj001-aml-default-storage-blob-to-vnt-cmn-pe")
            print("esmlproj001-aml-default-storage-file-to-vnt-cmn-pe")
            
            print(" - DSVM naming eaxmple")
            print("esmlcmn-dsvm-to-vnt-cmn-001")
            print("esmlproj001-dsvm-to-vnt-cmn-001")

    @property
    def environment_dictionary(self):
        return self.env_dict
