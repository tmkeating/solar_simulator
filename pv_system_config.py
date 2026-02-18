UAB_config = {
    'latitude': 41.500,
    'longitude': 2.112,
    'tz': 'Europe/Madrid',
    'altitude': 15+128,
    'name': 'EnginyeriaUAB',
    'tilt': 10.,
    'orientation': 225.
}

pv_module = {
    'name': 'JKM470N-60HL4-V (PRV)',
    'celltype': 'monoSi',
    'pdc0': 470,
    'v_mp': 35.05,
    'i_mp': 13.41,
    'v_oc': 42.38,
    'i_sc': 14.15,
    'alpha_sc': 0.00046*14.15,
    'beta_voc': -0.0025*42.38,
    'gamma_pdc': -0.3,
    'cells_in_series': 6*20,
    'temp_ref': 25,
    'numbercells': 6*20
}

pv_inverter = {
    'name': 'SUN2000-60KTL-M0_400Vac',
    'pdc0': 66000,
    'eta_inv_norm': 0.987,
    'eta_inv_ref': 0.9637
}
