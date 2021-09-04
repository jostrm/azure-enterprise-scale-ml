-- DEMO Azure SQL Database source for M11_Diabetes model

-- 1) IN DATA to Lake, anonymized
CREATE TABLE [dbo].[esml_diabetes]
(
    -- PersonId: Not needed for ML scoring. It is actually only noise for the Machine Learning brain. 
    PersonId INT IDENTITY(1,1) not null, -- But IF we want to reconnect scored RESULT to an individual, we need it.
	AGE FLOAT NOT NULL,
	SEX FLOAT NOT NULL,
	BMI FLOAT NOT NULL,
	BP FLOAT NOT NULL,
	S1 FLOAT NOT NULL,
	S2 FLOAT NOT NULL,
	S3 FLOAT NOT NULL,
	S4 FLOAT NOT NULL,
	S5 FLOAT NOT NULL,
	S6 FLOAT NOT NULL
)

-- 2) Scored data the PIPELINE WroteBack
CREATE TABLE [dbo].[esml_personID_scoring]
(
    PersonId INT NOT NULL,
    DiabetesMLScoring DECIMAL NULL,
    scoring_time DATETIME NULL,
    in_data_time DATETIME NULL,
    ts DATETIME NOT NULL DEFAULT (GETDATE())
)
-- SELECT Count(*) as total_rows FROM [dbo].[esml_personID_scoring] -- 442 rows per RUN since "UPSERT" from Azure Datafactory on PersonID
-- SELECT * FROM [dbo].[esml_personID_scoring]

-- 3) VIEW Person connected to scoring: Risk of DIABETES

--SELECT * FROM [dbo].[esml_diabetes] as a
SELECT * FROM [dbo].[esml_person_info] as a
LEFT JOIN [dbo].[esml_personID_scoring] as b
ON a.PersonId = b.PersonId