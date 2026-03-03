import time
import pvlib
import datetime
import pandas as pd
import influx_config # TODO - Pyhton script that contains configuration info of influx
import pv_system_config # TODO - Pyhton script that contains configuration info of the PhotoVoltaic cells

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from pvlib.location import Location
from pvlib.pvsystem import PVSystem, Array, FixedMount

execution_period = 2


def _get_specific_data(full_data, current_time, prev_time_data, prev_data):
    # Search for the surrounding data points in full_data matching current month/day/time
    target_time = current_time.replace(year=full_data.index[0].year)
    
    # Get the indices of the points before and after target_time
    idx_after = full_data.index.get_indexer([target_time], method='bfill')[0]
    idx_before = full_data.index.get_indexer([target_time], method='ffill')[0]

    # If target_time is exactly on a point, or we're at the very start/end
    if idx_after == idx_before or idx_after == -1 or idx_before == -1:
        idx = idx_after if idx_after != -1 else idx_before
        specific_data = full_data.iloc[idx].to_dict()
    else:
        # Perform linear interpolation: v(t) = v0 + (v1 - v0) * (t - t0) / (t1 - t0)
        t0 = full_data.index[idx_before]
        t1 = full_data.index[idx_after]
        v0 = full_data.iloc[idx_before]
        v1 = full_data.iloc[idx_after]
        
        # Ensure we only interpolate numeric values to avoid TypeError with strings
        v0_numeric = pd.to_numeric(v0, errors='coerce')
        v1_numeric = pd.to_numeric(v1, errors='coerce')
        
        # Calculate interpolation factor (progress between t0 and t1, 0.0 to 1.0)
        time_diff_total = (t1 - t0).total_seconds()
        time_diff_current = (target_time - t0).total_seconds()
        factor = time_diff_current / time_diff_total
        
        # Interpolate numeric columns and keep non-numeric as is from v0
        interpolated_values = v0_numeric + (v1_numeric - v0_numeric) * factor
        specific_data = v0.to_dict()
        for col in interpolated_values.index:
            if not pd.isna(interpolated_values[col]):
                specific_data[col] = interpolated_values[col]

    return specific_data, current_time

def _get_pv_structure(scenario_configuration, pv_module, modules_line, columns_array, name_array):
    scenario_mount = FixedMount(surface_tilt=scenario_configuration['tilt'],
                                surface_azimuth=scenario_configuration['orientation'],
                                module_height=scenario_configuration['altitude'])
    scenario_array = Array(mount=scenario_mount, module=pv_module['name'],
                           modules_per_string=modules_line, strings=columns_array, name=name_array)
    return scenario_array


def _get_effective_irradiance(scenario_config, solar_position, meteo_data):
    # Irradiance is in the 'values' column
    if meteo_data['values'] != 0:
        aoi_scenario = pvlib.irradiance.aoi(surface_tilt=scenario_config['tilt'], surface_azimuth=scenario_config['orientation'],
                                            solar_zenith=solar_position.apparent_zenith, solar_azimuth=solar_position.azimuth)
        iam_scenario = pvlib.iam.ashrae(aoi=aoi_scenario)
        effective_irradiance = meteo_data['values']*iam_scenario

    else:
        effective_irradiance = meteo_data['values']

    return effective_irradiance


def _get_temperature_cell(meteo_data):
    # This function requires Irradiance, Air Temperature and Wind Speed information.
    # Fallback to standard values for temp/wind if not present in CSV
    irradiance = meteo_data.get('values', 0)
    temp_air = meteo_data.get('Temperature', 20)
    wind_speed = meteo_data.get('Wind', 2)
    temp_cell = pvlib.temperature.faiman(irradiance, temp_air, wind_speed)
    return temp_cell


def _calculate_maximum_power_point(effective_irradiance, temp_cell, pv_module):
    I_L_ref, I_o_ref, R_s, R_sh_ref, a_ref, Adjust = pvlib.ivtools.sdm.fit_cec_sam(celltype=pv_module['celltype'],
                                                                                   v_mp=pv_module['v_mp'],
                                                                                   i_mp=pv_module['i_mp'],
                                                                                   v_oc=pv_module['v_oc'],
                                                                                   i_sc=pv_module['i_sc'],
                                                                                   alpha_sc=pv_module['alpha_sc'],
                                                                                   beta_voc=pv_module['beta_voc'],
                                                                                   gamma_pmp=pv_module['gamma_pdc'],
                                                                                   cells_in_series=pv_module['numbercells'],
                                                                                   temp_ref=pv_module['temp_ref'])
    cec_parameters = pvlib.pvsystem.calcparams_cec(effective_irradiance=effective_irradiance,
                                                   temp_cell=temp_cell,
                                                   alpha_sc=pv_module['alpha_sc'], a_ref=a_ref, I_L_ref=I_L_ref, I_o_ref=I_o_ref,
                                                   R_sh_ref=R_sh_ref, R_s=R_s, Adjust=Adjust)
    mpp_scenario = pvlib.pvsystem.max_power_point(*cec_parameters,
                                                  method='newton')
    return mpp_scenario


def _get_solarposition(scenario_location, current_time):
    solarpos = scenario_location.get_solarposition(times=pd.date_range(start=current_time,
                                                                       end=current_time,
                                                                       tz=datetime.timezone.utc))
    return solarpos


def _request_meteodata(_folder_data):
    data_format = '%Y-%m-%d %H:%M:%S'

    meteocat_df = pd.read_csv(_folder_data + 'meteo_full_df.csv', sep=',', decimal=',')
    # TODO -  Subtitute ... for Date Time column
    meteocat_df['DateTime'] = meteocat_df['DateTime'].apply(lambda x: pd.to_datetime(x, utc=True, format=data_format) + datetime.timedelta(minutes=30))
    # Convert values column to numeric, forcing errors to NaN if any strings remain
    meteocat_df['values'] = pd.to_numeric(meteocat_df['values'].astype(str).str.replace(',', '.'), errors='coerce')
    
    # Irradiance (values column) - replace negative values or NaNs with 0.0
    meteocat_df['values'] = meteocat_df['values'].apply(lambda x: 0. if pd.isna(x) or x < 0. else x)
    meteocat_df.set_index('DateTime', inplace=True)

    return meteocat_df


def _send_energy_to_influx_db(influx_conf, write_api, tag_id, report, timestamp=None):
    # DC and AC production to InfluxDB measurement 'solar_production'
    bucket = influx_conf.get('influx_database')
    if bucket is None or bucket is Ellipsis:
        bucket = 'solar_viz_bucket'
        
    point_to_store = Point("solar_production") \
        .tag("ID", tag_id) \
        .field("DC_Production", float(report['energyDCProduction'])) \
        .field("AC_Production", float(report['energyACProduction']))
    
    # If a timestamp is provided (simulated time), use it; otherwise use now
    if timestamp:
        # Crucial for v2: Ensure timestamp is converted to UTC nanosecond precision
        # or simplified to a DateTime object that the library can handle
        point_to_store.time(pd.to_datetime(timestamp).tz_convert('UTC'))
    
    try:
        write_api.write(bucket=bucket, record=point_to_store)
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Sent data for {timestamp or 'now'} to InfluxDB: "
              f"DC={report['energyDCProduction']:.2f}kW, AC={report['energyACProduction']:.2f}kW")
    except Exception as e:
        print(f"Failed to send data to InfluxDB: {e}")


def _get_influx_db(influx_conf):
    # Construct InfluxDB URL from configuration
    try:
        host = influx_conf.get('influx_host')
        if host is None or host is Ellipsis:
            host = 'localhost'
            
        port = influx_conf.get('influx_port')
        if port is None or port is Ellipsis:
            port = 8086
            
        org = influx_conf.get('influx_org')
        if org is None or org is Ellipsis:
            org = 'SolarBiz'
            
        url = f"http://{host}:{port}"
        client = InfluxDBClient(url=url, token=influx_conf['influx_token'], org=org)
    except Exception as e:
        print(f"Error connecting to InfluxDB: {e}")
        client = None
    return client


def main():
    influx_conf = influx_config.influx_db_config
    UAB_config = pv_system_config.UAB_config
    pv_module = pv_system_config.pv_module
    pv_inverter = pv_system_config.pv_inverter

    influx_db_client = _get_influx_db(influx_conf)
    write_influx_api = influx_db_client.write_api(write_options=SYNCHRONOUS)
    prev_time_UAB, meteo_data, effective_irradiance_UAB, meteo_specific_UAB = None, None, None, None
    location_UAB = Location(latitude=UAB_config['latitude'],
                            longitude=UAB_config['longitude'],
                            tz=UAB_config['tz'],
                            altitude=UAB_config['altitude'],
                            name=UAB_config['name'])
    UAB_array = _get_pv_structure(scenario_configuration=UAB_config, pv_module=pv_module,
                                  modules_line=18, columns_array=18, name_array='UAB')
    system_UAB = PVSystem(arrays=UAB_array)

    meteo_data = _request_meteodata(_folder_data='./WeatherData/Data/')
    data_year = meteo_data.index[0].year
    
    while True:
        time_now = datetime.datetime.now(datetime.timezone.utc)
        current_time = time_now.replace(year=data_year)

        meteo_specific_UAB, prev_time_UAB = _get_specific_data(meteo_data, current_time, prev_time_UAB,
                                                               meteo_specific_UAB)
        solarpos_UAB = _get_solarposition(scenario_location=location_UAB, current_time=current_time)

        # Use 'values' as the irradiance column
        if meteo_specific_UAB is not None and meteo_specific_UAB.get('values', 0) != 0:
            effective_irradiance_UAB = _get_effective_irradiance(scenario_config=UAB_config,
                                                                 solar_position=solarpos_UAB,
                                                                 meteo_data=meteo_specific_UAB)
            temp_cell_UAB = _get_temperature_cell(meteo_data=meteo_specific_UAB)

            production_UAB = _calculate_maximum_power_point(effective_irradiance=effective_irradiance_UAB,
                                                            temp_cell=temp_cell_UAB,
                                                            pv_module=pv_module)
            dc_production_UAB = system_UAB.scale_voltage_current_power(production_UAB)
            dc_production_UAB_val = dc_production_UAB.iloc[0].p_mp / 1000
            production_ac_UAB = pvlib.inverter.pvwatts(pdc=dc_production_UAB.p_mp,
                                                       pdc0=pv_inverter['pdc0'],
                                                       eta_inv_nom=pv_inverter['eta_inv_norm'],
                                                       eta_inv_ref=pv_inverter['eta_inv_ref'])
            production_ac_UAB_val = list(production_ac_UAB)[0] / 1000

        else:
            dc_production_UAB_val = 0.
            production_ac_UAB_val = 0.

        report_energy = {
            'energyACProduction': production_ac_UAB_val,
            'energyDCProduction': dc_production_UAB_val,
        }
        _send_energy_to_influx_db(influx_conf=influx_conf, write_api=write_influx_api, tag_id='UAB_Enginyeria',
                                  report=report_energy, timestamp=time_now)
        time.sleep(execution_period)


if __name__ == '__main__':
    main()
