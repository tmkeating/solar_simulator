import time
import pvlib
import datetime
import pandas as pd
import ... # TODO - Pyhton script that contains configuration info of influx
import ... # TODO - Pyhton script that contains configuration info of the PhotoVoltaic cells

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from pvlib.location import Location
from pvlib.pvsystem import PVSystem, Array, FixedMount

execution_period = 300


def _get_specific_data(full_data, current_time, prev_time_data, prev_data):
    # TODO - Specific data must be a dictionary with column name as key and the corresponding value as value
    if prev_time_data is None:
        prev_time_data = current_time.replace(hour=current_time.hour-1)

    # TODO - Return closest data, in 30min intervals, to the requested date after prev_data
    specific_data = {'CodiEstacio': 'XV', 'RelativeHumidityMax': 83.0, 'Wind': 2.2, 'WindDirection': 141.0,
                     'Temperature': 17.5, 'RelativeHumidity': 80.0, 'Rain': 0.0, 'Irradiance': 203.0,
                     'TemperatureMax': 18.2, 'TemperatureMin': 17.0, 'RelativeHumidityMin': 76.0,
                     'WindGust': 5.4, 'WindDirectionGust': 163.0, 'RainMax': 0.0}
    return specific_data, prev_time_data


def _get_pv_structure(scenario_configuration, pv_module, modules_line, columns_array, name_array):
    scenario_mount = FixedMount(surface_tilt=scenario_configuration['tilt'],
                                surface_azimuth=scenario_configuration['orientation'],
                                module_height=scenario_configuration['altitude'])
    scenario_array = Array(mount=scenario_mount, module=pv_module['name'],
                           modules_per_string=modules_line, strings=columns_array, name=name_array)
    return scenario_array


def _get_effective_irradiance(scenario_config, solar_position, meteo_data):
    # TODO - Substitute ... to the name of the column that contains Irradiance
    if meteo_data[...] != 0:
        aoi_scenario = pvlib.irradiance.aoi(surface_tilt=scenario_config['tilt'], surface_azimuth=scenario_config['orientation'],
                                            solar_zenith=solar_position.apparent_zenith, solar_azimuth=solar_position.azimuth)
        iam_scenario = pvlib.iam.ashrae(aoi=aoi_scenario)
        effective_irradiance = meteo_data[...]*iam_scenario

    else:
        effective_irradiance = meteo_data[...]

    return effective_irradiance


def _get_temperature_cell(meteo_data):
    # TODO - This function requires Irradiance, Air Temperature and Wind Speed information.
    temp_cell = pvlib.temperature.faiman(meteo_data[...],
                                         meteo_data[...],
                                         meteo_data[...])
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

    meteocat_df = pd.read_csv(_folder_data + 'meteo_full_df.csv', sep=';')
    # TODO -  Subtitute ... for Date Time column
    meteocat_df[...] = meteocat_df[...].apply(lambda x: pd.to_datetime(x, utc=True, format=data_format) + datetime.timedelta(minutes=30))
    # TODO -  Subtitute ... for Irradiance column
    meteocat_df[...] = meteocat_df[...].apply(lambda x: 0. if x < 0. else x)
    meteocat_df.set_index(..., inplace=True)

    return meteocat_df


def _send_energy_to_influx_db(influx_conf, write_api, tag_id, report):
    # TODO - Write (DC and AC production) to InfluxDB, in an appropiate _mesurement, _field and ID
    # TODO - Optionally indicate the correct type for the values to the DB
    point_to_store = (...)
    write_api.(...)


def _get_influx_db(influx_conf):
    # TODO - Correct port
    try:
        client = InfluxDBClient(url="http://localhost:...", token=influx_conf['influx_token'], org=influx_conf['influx_org'])
    except:
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
    while True:
        time_now = datetime.datetime.now(datetime.timezone.utc)
        current_time = time_now.replace(year=2020)

        meteo_specific_UAB, prev_time_UAB = _get_specific_data(meteo_data, current_time, prev_time_UAB,
                                                               meteo_specific_UAB)
        solarpos_UAB = _get_solarposition(scenario_location=location_UAB, current_time=current_time)

        # TODO -  Subtitute ... for Irradiance column
        if meteo_specific_UAB is not None and meteo_specific_UAB[...] != 0:
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
                                  report=report_energy)
        time.sleep(execution_period)


if __name__ == '__main__':
    main()
