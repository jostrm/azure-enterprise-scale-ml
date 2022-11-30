# Databricks notebook source
def split_last_n_by_grain(df,train_end,test_start, test_end,time_column_name):
    """Group df by grain and split on last n rows for each group."""
    df_grouped = (df.sort_values(time_column_name) # Sort by ascending time
                  .groupby(grain_column_names, group_keys=False))
    df_head = df_grouped.apply(lambda dfg: dfg[dfg[time_column_name] <= train_end])
    df_tail = df_grouped.apply(lambda dfg: dfg[(dfg[time_column_name] >= test_start) & ( dfg[time_column_name] < test_end)] )
    return df_head, df_tail

# COMMAND ----------

def align_outputs(y_predicted, X_trans, X_test, y_test,target_column_name, predicted_column_name='predicted',
                  horizon_colname='horizon_origin'):
    """
    Demonstrates how to get the output aligned to the inputs
    using pandas indexes. Helps understand what happened if
    the output's shape differs from the input shape, or if
    the data got re-sorted by time and grain during forecasting.
    
    Typical causes of misalignment are:
    * we predicted some periods that were missing in actuals -> drop from eval
    * model was asked to predict past max_horizon -> increase max horizon
    * data at start of X_test was needed for lags -> provide previous periods
    """
    df_fcst = pd.DataFrame({predicted_column_name : y_predicted})
    # y and X outputs are aligned by forecast() function contract
    df_fcst.index = X_trans.index
    
    # align original X_test to y_test    
    X_test_full = X_test.copy()
    X_test_full[target_column_name] = y_test

    # X_test_full's index does not include origin, so reset for merge
    df_fcst.reset_index(inplace=True)
    X_test_full = X_test_full.reset_index().drop(columns='index')
    together = df_fcst.merge(X_test_full, how='right')
    
    # drop rows where prediction or actuals are nan 
    # happens because of missing actuals 
    # or at edges of time due to lags/rolling windows
    clean = together[together[[target_column_name, predicted_column_name]].notnull().all(axis=1)]
    return(clean)

# COMMAND ----------

from pandas.tseries.frequencies import to_offset
def do_rolling_forecast(fitted_model, X_test, y_test, max_horizon, time_column_name,target_column_name,freq='H'): # D, W
    """
    Produce forecasts on a rolling origin over the given test set.
    
    Each iteration makes a forecast for the next 'max_horizon' periods 
    with respect to the current origin, then advances the origin by the horizon time duration. 
    The prediction context for each forecast is set so that the forecaster uses 
    the actual target values prior to the current origin time for constructing lag features.
    
    This function returns a concatenated DataFrame of rolling forecasts.
     """
    print("do_rolling_forecastfreq], ", freq)
    df_list = []
    origin_time = X_test[time_column_name].min()
    while origin_time <= X_test[time_column_name].max():
        # Set the horizon time - end date of the forecast
        horizon_time = origin_time + max_horizon * to_offset(freq)
        
        # Extract test data from an expanding window up-to the horizon 
        expand_wind = (X_test[time_column_name] < horizon_time)
        X_test_expand = X_test[expand_wind]
        y_query_expand = np.zeros(len(X_test_expand)).astype(np.float)
        y_query_expand.fill(np.NaN)
        
        if origin_time != X_test[time_column_name].min():
            # Set the context by including actuals up-to the origin time
            test_context_expand_wind = (X_test[time_column_name] < origin_time)
            context_expand_wind = (X_test_expand[time_column_name] < origin_time)
            y_query_expand[context_expand_wind] = y_test[test_context_expand_wind]
        
        # Make a forecast out to the maximum horizon
        y_fcst, X_trans = fitted_model.forecast(X_test_expand, y_query_expand)
        
        # Align forecast with test set for dates within the current rolling window 
        trans_tindex = X_trans.index.get_level_values(time_column_name)
        trans_roll_wind = (trans_tindex >= origin_time) & (trans_tindex < horizon_time)
        test_roll_wind = expand_wind & (X_test[time_column_name] >= origin_time)
        df_list.append(align_outputs(y_fcst[trans_roll_wind], X_trans[trans_roll_wind],
                                     X_test[test_roll_wind], y_test[test_roll_wind],target_column_name))
        
        # Advance the origin time
        origin_time = horizon_time
    
    return pd.concat(df_list, ignore_index=True)

# COMMAND ----------

#  out_dir_prediction_error_percent[time_string] = round((abs(y_fcst.sum() - y_test.sum()) / y_test.sum()) * 100,2)
def MAPE(actual, pred):
    """
    Calculate mean absolute percentage error.
    Remove NA and values where actual is close to zero
    """
    not_na = ~(np.isnan(actual) | np.isnan(pred))
    not_zero = ~np.isclose(actual, 0.0)
    actual_safe = actual[not_na & not_zero]
    pred_safe = pred[not_na & not_zero]
    APE = 100*np.abs((actual_safe - pred_safe)/actual_safe)
    return np.mean(APE)

# COMMAND ----------

def rolling_evaluation(fitted_model, X_test, y_test, max_horizon, rolling,time_column_name,frequency):
  
  if (rolling): 
    df_all = do_rolling_forecast(fitted_model, X_test, y_test, max_horizon,time_column_name, frequency) # Forecasts + Aligns
    print ("Rolling, rolling, rolling..")
    return df_all
  else:
    y_predback, X_trans = fitted_model.forecast(X_test, y_pred)   # "The length of y_pred is different from the X_pred"  ( X_pred, y_pred)  / "No y values were provided."
    df_all = align_outputs(y_predback, X_trans, X_test, y_test) # Align
    print ("NOT rolling")
    return df_all
  
#df_all

# COMMAND ----------

def interpolate_hourly(df_in, time_colname):
  #df_in.reset_index(inplace=True)
  full_idx = pd.date_range(start=df_in[time_column_name].min(), end=df_in[time_column_name].max(), freq='60T') # 60min
  
  df_in.set_index(time_column_name, inplace=True)
  df = df_in.reindex(full_idx, method='nearest').reset_index(level=0, drop=False).sort_index()
  df.rename(columns={'index':time_colname},inplace=True)
  return df

# COMMAND ----------

def get_missing_dates(df2, start_date, end_date,time_column_name):
  df2.set_index(time_column_name,inplace=True)
  
  # Note date_range is inclusive of the end date. 
  ref_date_range = pd.date_range(start_date,end_date, freq='60Min')  # ‘2014–2–8 23:30:00’
  ref_df = pd.DataFrame(np.random.randint(1, 20, (ref_date_range.shape[0], 1)))
  ref_df.index = ref_date_range
  # check for missing datetimeindex values based on reference index (with all values)
  missing_dates = ref_df.index[~ref_df.index.isin(df2.index)]
  df2.reset_index(inplace=True)
  return missing_dates

# COMMAND ----------

# MAGIC %md
# MAGIC ## Imported...Time series support functions: Grain split, alignment, MAPE, rolling eval, ts functions

# COMMAND ----------


