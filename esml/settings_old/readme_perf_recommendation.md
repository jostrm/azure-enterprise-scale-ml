# Guidlines & Recommendations
## Disclaimer: 
- These are my collected experience, partly from Azure certifications (and Databricks certifications), and partly from practical hands-on experience (read 'headache')
- They are to be treated as guidlines & tips. If you as a company want adapt and coher to thats of course your decision.  / Joakim Åström, Microsoft
- and...
`
Copyright (C) Microsoft Corporation. All rights reserved.​
 ​
Microsoft Corporation (“Microsoft”) grants you a nonexclusive, perpetual,
royalty-free right to use, copy, and modify the software code provided by us
("Software Code"). You may not sublicense the Software Code or any use of it
(except to your affiliates and to vendors to perform work on your behalf)
through distribution, network access, service agreement, lease, rental, or
otherwise. This license does not purport to express any claim of ownership over
data you may have shared with Microsoft in the creation of the Software Code.
Unless applicable law gives you more rights, Microsoft reserves all other
rights not expressly granted herein, whether by implication, estoppel or
otherwise. ​
 ​
THE SOFTWARE CODE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
MICROSOFT OR ITS LICENSORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR
BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER
IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THE SOFTWARE CODE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
`

# Q: Hm...what VM type should you choose in DEV, TEST, PROD for clusters? 

# GENERALLY SPEAKING "right-sizing" - not specific to `dev,test,prod`

Q1: How to "right-size" What RAM on train/inference/batch compute - Azure VM type? 
- A: One CSV file of size 1GB can become 10GB as a pandas DATAFRAME. You always want double that "buffer", to have 20GB RAM available on the "node" that aggregates GOLD dataframe
- Example of VM types:
    - Memory optimized: `Standard_DS13_v2` (8 cores, `56GB RAM`, 112GB storage)
        - Can handle a GOLD dataset of `2.5 GB csv file` -> which can become 25GB in RAM, then you have ~double that max
    - General purpose: `Standard_DS4_v2` (8 cores, `28GB RAM`, 56GB storage)
        - Can handle a GOLD dataset from `1 GB CSV file`
- Tip: Right-size for your RAM to have data from `IN->Bronze->Silver->GOLD`, at least to hold `GOLD` in memory. At the principle of formula `IN_size.csv *10*2`

Q2: How about .parquet files, or Spark cluster? 
 - These are more efficient, but same principle - if you need to AGGREGATE data to "GOLD", the worker nodes is no use, since aggregation is on the "driver" (executor) node - focus on RAM here.

Q1, Q2 Tip - You can always "Trade" RAM for "DISK and slower performance"
  - Example: pandas.read_parquet()
 - See how you can Trade 50% RAM (1700MB -> 780MB) for 2x disk IO time (5.8min -> 10.2min runtime)
    - Example: https://www.kaggle.com/jamesmcguigan/reading-parquet-files-ram-cpu-optimization

Q3: On AKS, I get a "memory error"
- A: Try turn on auto-scaling, or scale manually on nodes, or increase VM-type

# DEV vs TEST and PROD - Ways of working = save cost

Q1: What RAM/CORES on train/inference/batch compute for DEV, when I'm in R&D/PoC phase? 
- A: This is about way of working. Here you can save costs. 
    - You should have at least 2 cluster sizes (small, right-sized). 
    - 1)Use the `SMALL` cluster: When you are in the PoC phase, and create your code base (debugging, feature engineering, test training settings) 
        - Q: But my IN-data it too big, I cannot read it to ram with SMALL cluster?
        - A: `You should filter your IN-data when in "debugging / rnd" mode` - then the SMALL cluster works. Filter IN to work  `IN->Bronze->Silver->GOLD`
            - In ESML you can set the `project.rnd=True` flag and it will filter IN-data automatically to use 20% only. (Also no versioning on Azure ML dataset is used then)
    - 2)Use the `RIGHT-SIZED` cluster: When you are in the PoC phase, and are doing the real training runs, to get good scoring
        - `In ESML you can easily swith to TEST environment where you should have the "right-sized" settings`, same as in PROD.
            - See exampel notebooks, and the statemet `p.dev_test_prod = "test"`

Q2: I get AKS error that fails, stating something about too much cores and RAM? 
- Example: WebserviceException: Deployment request failed due to insufficient compute resource. For the specified compute target, 1 replica cannot be created per specified CPU/Memory configuration(6 CPU Cores, 10GB Memory)
 - A: If you are in `AKS-DevTest mode, only 1 node/replica is used.` If you have I node of VM type `Standard_DS13_v2` (8 cores, `56GB RAM`, 112GB storage), you cannot have more than 8 cores.
 - Example: If you have below in your SETTINGS, this means you can deploy 4 models/webservices on the same AKS-cluster, until you hit CPU core limit of 8 cores (4*2=8) for that AKS cluster
     - `"aks_cpu_cores": 2,`
     - `"aks_memory_gb": 10,`
 - Note: If 56GB ram on VM type, and `aks_memory_db` set to 7 then 8 webservices can run on such node/replica.
    - ` If not DevTest: AKS will scale from 1-M nodes. If 4 nodes -> 224B RAM and 32 cores`
    - Tip: In TEST and PROD: If using an uneven / odd number, it will autoscale with more margin to add new replicas
         - Example `Standard_DS13_v2` (8 cores, `56GB RAM`, 112GB storage): 
            - Per replica: `7 cores`, 24 GB Ram

# Architecture
## Scenario: Consuming application, to to call my model with low latency? (200 000 calls, response under 0.061 seconds)
- Q: Workload: 200 000 calls with response of 0.061 seconds in Average?
- A: Use Cosmos DB as a cache, together with model deployed on AKS. (or Azure Cache for Redis)
- https://docs.microsoft.com/en-us/azure/architecture/reference-architectures/ai/real-time-recommendation

