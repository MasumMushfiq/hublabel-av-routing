# Electric Energy and Emissions Assumptions

This file records the source references and rationale for the electric-energy parameters used in the AV feeder simulation experiments.

## Modeling decision

The main experiments model all vehicles as electric:

- AV scooter
- AV moped
- AV car
- AV minibus/shuttle
- fallback private car
- private-car baseline

This avoids mixing petrol, diesel, and electricity assumptions and keeps the comparison focused on fleet composition, pooling, routing, and vehicle-type tradeoffs.

The private-car baseline is therefore interpreted as an electric private-car baseline: every commuter drives an electric private car to the station. The fallback private-car users are also modeled as electric private cars.

---

## Global electricity assumptions

### Electricity emission factor

Parameter:

```json
"grid_co2_kg_per_kwh": 0.78
```

Source:

- Australian Government Department of Climate Change, Energy, the Environment and Water, *National Greenhouse Accounts Factors 2025*.

Rationale:

- The National Greenhouse Accounts Factors provide official Australian electricity-emission factors.
- For Victoria, the 2025 location-based Scope 2 electricity factor is 0.78 kg CO2-e/kWh.
- This converts electricity consumption in kWh into CO2-e emissions.

Reference:

- https://www.dcceew.gov.au/sites/default/files/documents/national-greenhouse-account-factors-2025.pdf

Notes:

- Scope 2 is used for the main experiments.
- Scope 3 electricity factors can be considered later only as a sensitivity analysis if needed.

### Electricity price

Parameter:

```json
"electricity_cost_per_kwh": 0.27
```

Source:

- EnergyPlans, *Victoria electricity prices 2026*.

Rationale:

- The reported average Victorian electricity usage rate is 26.8 c/kWh.
- We round this to AUD 0.27/kWh for the base experiment.
- This is used only for energy operating cost, not for routing optimization.

Reference:

- https://www.energyplans.com.au/electricity-prices/vic

---

## Vehicle energy-consumption assumptions

### Electric scooter

Parameter:

```json
"energy_kwh_per_km": 0.016
```

Source:

- Jia, R. et al. (2025), *Life-cycle analysis of shared e-scooter: data-driven approaches in 100 EU cities*, Transportation Research Part D.

Rationale:

- The study reports operational e-scooter active-riding energy consumption of 15.9 Wh/km.
- We convert 15.9 Wh/km to 0.0159 kWh/km and round to 0.016 kWh/km.
- This value is used for the single-passenger electric scooter class.

Reference:

- https://www.sciencedirect.com/science/article/pii/S1361920925004195

### Electric moped

Parameter:

```json
"energy_kwh_per_km": 0.058
```

Source:

- Kusalaphirom, T., Satiennam, T., and Satiennam, W. (2023), *Factors Influencing the Real-World Electricity Consumption of Electric Motorcycles*, Energies, 16(17), 6369.

Rationale:

- The study collected real-world electric motorcycle consumption data from 105 participants.
- It reports mean electricity consumption of 57.83 Wh/km.
- We convert 57.83 Wh/km to 0.05783 kWh/km and round to 0.058 kWh/km.
- This value is used for the two-passenger electric moped/light motorcycle class.

Reference:

- https://www.mdpi.com/1996-1073/16/17/6369

### Electric car / private car baseline

Parameter:

```json
"energy_kwh_per_km": 0.155
```

Source:

- EV Database / EV model specifications for Tesla Model 3 Long Range AWD.

Rationale:

- The Tesla Model 3 Long Range AWD is a representative efficient electric passenger car.
- Reported real-world consumption is approximately 155 Wh/km.
- We convert 155 Wh/km to 0.155 kWh/km.
- This value is used for both AV cars and the electric private-car baseline/fallback.

References:

- https://ev-database.org/car/1321/Tesla-Model-3-Long-Range-AWD
- https://ev-database.org/cheatsheet/energy-consumption-electric-car

### Electric minibus / shuttle

Parameter:

```json
"energy_kwh_per_km": 0.330
```

Source:

- Dewesoft, *Evaluating Energy Consumption of Electric Minibus*.

Rationale:

- The electric minibus evaluation reports specific consumption of 0.33 kWh/km.
- This is used for the electric minibus/shuttle vehicle class.
- The value is appropriate for a smaller electric minibus/shuttle rather than a full-size city bus.

Reference:

- https://dewesoft.com/blog/evaluating-energy-consumption-of-electric-minibus

---

## Current base parameter set

```json
{
  "energy_model": {
    "electricity_cost_per_kwh": 0.27,
    "grid_co2_kg_per_kwh": 0.78,
    "emission_factor_region": "Victoria",
    "emission_factor_scope": "Scope 2 location-based",
    "emission_factor_source": "Australian National Greenhouse Accounts Factors 2025",
    "energy_cost_source": "Victoria average electricity usage rate, 2026"
  },
  "vehicle_energy": {
    "scooter": {
      "energy_kwh_per_km": 0.016,
      "source_value": "15.9 Wh/km",
      "source": "Jia et al. (2025), shared e-scooter operational data"
    },
    "moped": {
      "energy_kwh_per_km": 0.058,
      "source_value": "57.83 Wh/km",
      "source": "Kusalaphirom et al. (2023), real-world electric motorcycle consumption"
    },
    "car": {
      "energy_kwh_per_km": 0.155,
      "source_value": "155 Wh/km",
      "source": "EV Database / Tesla Model 3 Long Range AWD"
    },
    "minibus": {
      "energy_kwh_per_km": 0.330,
      "source_value": "0.33 kWh/km",
      "source": "Dewesoft electric minibus evaluation"
    },
    "private_car_baseline": {
      "energy_kwh_per_km": 0.155,
      "source_value": "155 Wh/km",
      "source": "EV Database / Tesla Model 3 Long Range AWD"
    },
    "fallback_private_car": {
      "energy_kwh_per_km": 0.155,
      "source_value": "155 Wh/km",
      "source": "Same as private-car baseline"
    }
  }
}
```

---

## Suggested config field names

The main configuration should use energy terms rather than fuel terms.

Vehicle-type field:

```json
"energy_kwh_per_km": 0.155
```

Global energy model:

```json
"energy_model": {
  "electricity_cost_per_kwh": 0.27,
  "grid_co2_kg_per_kwh": 0.78
}
```

Private-car baseline:

```json
"private_car_energy_kwh_per_km": 0.155
```

---

## Conversion formulas

Energy consumption:

```text
energy_kwh = vehicle_km × energy_kwh_per_km
```

Electricity cost:

```text
energy_cost_aud = energy_kwh × electricity_cost_per_kwh
```

Emissions:

```text
co2_kg = energy_kwh × grid_co2_kg_per_kwh
```

Adjusted AV energy:

```text
adjusted_av_total_energy_kwh =
    sum over AV vehicle types and adjusted post-pruning vehicle kilometers
```

Fallback private-car energy:

```text
fallback_private_car_energy_kwh =
    fallback_private_car_vmt_km × private_car_energy_kwh_per_km
```

System-level energy:

```text
system_total_energy_kwh =
    adjusted_av_total_energy_kwh
  + fallback_private_car_energy_kwh
```

System-level emissions:

```text
system_total_co2_kg =
    adjusted_av_total_co2_kg
  + fallback_private_car_co2_kg
```

Energy cost:

```text
av_energy_cost =
    adjusted_av_total_energy_kwh × electricity_cost_per_kwh
```

---

## Metric naming recommendation

Recommended new energy fields:

```text
raw_av_total_energy_kwh
adjusted_av_total_energy_kwh
fallback_private_car_energy_kwh
system_total_energy_kwh
baseline_total_energy_kwh

energy_change_pct
system_energy_change_pct

av_energy_cost
fallback_private_car_energy_cost
system_energy_cost
baseline_energy_cost
```

Existing CO2 fields can remain, but their formula should be based on electricity consumption:

```text
co2_kg = energy_kwh × grid_co2_kg_per_kwh
```

The paper should use energy terminology rather than fuel terminology.

---

## Paper wording draft

All vehicles are modeled as electric vehicles to reflect the likely deployment context of future autonomous feeder systems and to avoid mixing petrol, diesel, and electricity assumptions. Energy use is computed from distance traveled and vehicle-specific electricity consumption rates. Emissions are estimated using the Victorian electricity-grid emission factor from the Australian National Greenhouse Accounts Factors, and energy cost is calculated using an average Victorian electricity price. This keeps the private-car baseline, fallback private-car users, and AV feeder fleet on a consistent energy basis.

---

## BibTeX-style reference notes

```bibtex
@misc{DCCEEW2025NGA,
  title = {National Greenhouse Accounts Factors 2025},
  author = {{Australian Government Department of Climate Change, Energy, the Environment and Water}},
  year = {2025},
  url = {https://www.dcceew.gov.au/sites/default/files/documents/national-greenhouse-account-factors-2025.pdf}
}

@misc{EnergyPlansVictoria2026,
  title = {Victoria Electricity Prices 2026},
  author = {{EnergyPlans.com.au}},
  year = {2026},
  url = {https://www.energyplans.com.au/electricity-prices/vic}
}

@article{Jia2025EScooterLCA,
  title = {Life-cycle analysis of shared e-scooter: data-driven approaches in 100 EU cities},
  author = {Jia, R. and others},
  year = {2025},
  journal = {Transportation Research Part D},
  url = {https://www.sciencedirect.com/science/article/pii/S1361920925004195}
}

@article{Kusalaphirom2023ElectricMotorcycle,
  title = {Factors Influencing the Real-World Electricity Consumption of Electric Motorcycles},
  author = {Kusalaphirom, Triluck and Satiennam, Thaned and Satiennam, Wichuda},
  journal = {Energies},
  volume = {16},
  number = {17},
  pages = {6369},
  year = {2023},
  doi = {10.3390/en16176369},
  url = {https://www.mdpi.com/1996-1073/16/17/6369}
}

@misc{EVDatabaseTeslaModel3,
  title = {Tesla Model 3 Long Range AWD energy consumption},
  author = {{EV Database}},
  url = {https://ev-database.org/car/1321/Tesla-Model-3-Long-Range-AWD}
}

@misc{EVDatabaseConsumptionCheatSheet,
  title = {Electric vehicle energy consumption cheat sheet},
  author = {{EV Database}},
  url = {https://ev-database.org/cheatsheet/energy-consumption-electric-car}
}

@misc{DewesoftElectricMinibus,
  title = {Evaluating Energy Consumption of Electric Minibus},
  author = {{Dewesoft}},
  url = {https://dewesoft.com/blog/evaluating-energy-consumption-of-electric-minibus}
}
```

---

## Implementation checklist

When converting the codebase from fuel to electricity, update:

1. `config/legacy_melton_base_config.json`
   - replace `fuel_l_per_100km` with `energy_kwh_per_km`
   - replace private-car fuel fields with private-car energy fields
   - add or update `energy_model`

2. Dataclasses/config loader
   - update `VehicleConfig`
   - update `ExperimentConfig`
   - preserve backward compatibility only if needed temporarily

3. Baseline calculation
   - compute baseline energy from private-car VMT
   - compute baseline CO2 from energy × grid factor

4. AV route metrics
   - compute raw and adjusted AV energy from vehicle-type VMT
   - compute AV CO2 from energy × grid factor

5. Fallback private-car metrics
   - compute fallback private-car energy from fallback VMT
   - compute fallback CO2 from energy × grid factor

6. System metrics
   - compute system energy and CO2 as adjusted AV + fallback private car

7. Cost model
   - replace fuel cost with energy cost
   - use electricity price per kWh
   - keep fixed fleet cost and distance-based operating cost separate

8. Plotting and aggregation scripts
   - update labels from fuel to energy
   - use energy fields in summaries
   - keep CO2 fields but note that they are electricity-based

9. Tests
   - update utility tests for baseline, comparison, cost, and fallback metrics

10. Paper wording
   - remove petrol/diesel language
   - describe all vehicles as electric
   - describe emissions as grid-electricity-based
