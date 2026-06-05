# Electric AV Fleet Cost Assumptions Reference

**Project:** Heterogeneous electric AV feeder fleet for first-mile access to Melton Station  
**Purpose:** defensible, transparent cost assumptions for evaluation-only cost metrics  
**Recommended repository path:** `docs/cost_assumptions_reference.md`  
**Status:** base-case values ready for `config/base_config.json` after review  

---

## 1. Scope and interpretation

The cost model is used for **post-routing evaluation only**. It is intended to compare heterogeneous fleet compositions after service, VMT, energy, and emissions metrics have already been computed. It should **not** affect the routing objective, solver behavior, pruning logic, time-window logic, or emissions formulas.

The base cost model includes:

- vehicle platform capital cost,
- annualized capital cost converted to a per-service-day fixed cost,
- non-energy maintenance cost per kilometre,
- electricity cost from the separate energy model.

The base cost model excludes:

- driver labour, because all fleet modes are modeled as autonomous vehicles,
- explicit autonomy-stack hardware/software premiums,
- depot land and charging-infrastructure capital cost,
- insurance, registration, and regulatory compliance costs,
- remote operations / fleet supervision labour.

Because these excluded categories can be substantial, the cost outputs should be described as **indicative operating-cost indicators for relative fleet comparison**, not as a complete deployment-ready business case.

---

## 2. Critical implementation rule

The current code separates evaluation cost from routing cost.

### Use these fields for AUD cost evaluation

```json
"cost_model": {
  "fixed_cost_per_vehicle": {
    "Scooter": 1.98,
    "Moped": 4.02,
    "Car": 39.96,
    "Minibus": 42.59
  },
  "maintenance_cost_per_km": {
    "Scooter": 0.06,
    "Moped": 0.04,
    "Car": 0.04,
    "Minibus": 0.25
  }
}
```

### Do not put AUD cost values here

```json
"fixed_cost_km_equiv"
```

`fixed_cost_km_equiv` belongs to `fleet.vehicle_types[]` and is used by the PyVRP solver objective as a kilometre-equivalent routing penalty. It must remain unchanged unless a future experiment explicitly changes the optimization objective. Putting AUD fixed costs into `fixed_cost_km_equiv` would change routing decisions and invalidate the evaluation-only cost assumption.

Electricity price remains in the energy model, not in the vehicle-level maintenance-cost fields.

---

## 3. Capital-cost annualization method

Vehicle capital cost is annualized using the capital recovery factor (CRF):

```text
CRF = r(1+r)^n / ((1+r)^n - 1)
annualized_capital_cost = purchase_price × CRF
fixed_cost_per_service_day = annualized_capital_cost / service_days_per_year
```

where:

- `r` is the real discount rate,
- `n` is the economic life in years.

### Discount rate

Base case:

```json
"cost_discount_rate": 0.07
```

Rationale:

- The Australian Government Office of Impact Analysis cost-benefit analysis guidance requires net present values to be calculated at a central annual real discount rate of 7%.
- The same guidance recommends sensitivity analysis at 3% and 10%.

Reference:

- Australian Government Office of Impact Analysis. *Cost Benefit Analysis*.  
  https://oia.pmc.gov.au/resources/guidance-assessing-impacts/cost-benefit-analysis

### Service days per year

Base case:

```json
"service_days_per_year": 250
```

Rationale:

- The Melton experiment represents weekday morning-peak station access.
- A 250-day service year approximates five weekdays per week over 50 operating weeks.
- This converts annualized capital cost into a daily fixed fleet cost for the one-day simulation.

The resulting daily value should be interpreted as a representative weekday fixed cost. It is not intended to represent a full annual business account unless the same weekday service pattern is repeated for 250 service days.

---

## 4. Vehicle purchase-cost and life assumptions

All monetary values are Australian dollars (AUD). Retail prices and dealer listings are market references and should be cited with access dates in the paper or supporting material.

| Vehicle class | Purchase cost (AUD) | Economic life (yr) | Main rationale |
|---|---:|---:|---|
| Scooter | 1,300 | 3 | Mid-range Australian e-scooter retail price; short fleet-use life due to battery and component wear. |
| Moped | 6,000 | 8 | Road-registered electric moped/light electric motorcycle proxy, between low-end and higher-spec Australian market references. |
| Car | 59,648 | 8 | Tesla Model 3 Australian price proxy, consistent with electric-car energy assumptions. |
| Minibus | 96,980 | 15 | Small electric minibus / shuttle proxy; 15-year life follows bus-class assumption for vehicles above 3.5 t GVM. |

### Scooter

Base purchase cost:

```json
"purchase_price_aud": 1300
```

Rationale:

- The modeled scooter is a single-passenger low-speed electric micromobility vehicle.
- NIU KQi 300P Australian retail listings show a price of about AUD 1,299.95.
- A 3-year life is a conservative fleet-use assumption reflecting battery and component wear under repeated use.

References:

- BIG W. *NIU KQi 300P Electric Scooter*.  
  https://www.bigw.com.au/product/niu-kqi-300p-electric-scooter/p/9902729067
- BIG W / Electric Kicks marketplace listing. *NIU KQi 300P Electric Scooter - Black*.  
  https://www.bigw.com.au/product/niu-kqi-300p-electric-scooter-black/p/9902729068

### Moped / light electric motorcycle

Base purchase cost:

```json
"purchase_price_aud": 6000
```

Rationale:

- The modeled moped is a two-passenger, road-registered light electric two-wheeler with speed higher than a kick scooter.
- ROLL'N electric mopeds show Australian prices around AUD 4,350--4,950 depending on model.
- RedBook lists the 2025 Super Soco CPX electric scooter with price when new of AUD 7,690.
- AUD 6,000 is a middle value between entry-level electric mopeds and higher-spec Super Soco-style electric scooter/motorcycle references.
- An 8-year economic life is used by analogy with motor vehicle / motorcycle effective-life assumptions; if the exact current ATO motorcycle row is used in the paper, verify against the current effective-life determination.

References:

- ROLL'N. *Electric Mopeds in Australia*.  
  https://rollnmopeds.com.au/
- RedBook. *2025 Super Soco CPX MY21*.  
  https://www.redbook.com.au/bikes/details/2025-super-soco-cpx-my21/SPOT-ITM-658853/

### Electric car and private-car baseline

Base purchase cost:

```json
"purchase_price_aud": 59648
```

Rationale:

- The simulation uses an electric passenger-car platform for the AV car, fallback private car trips, and private-car baseline.
- The Tesla Model 3 is also used as the electric-car reference in the energy assumptions document, so keeping the same class is internally consistent.
- CarExpert lists the 2026 Tesla Model 3 in Australia from AUD 59,648 drive-away, with variant prices up to AUD 86,948.
- This base case is conservative-high relative to cheaper Australian EVs. If cost results become a major finding, a lower-cost EV sensitivity should be considered.

Reference:

- CarExpert. *2026 Tesla Model 3 Pricing*.  
  https://www.carexpert.com.au/tesla/model-3/2026/price-and-specs

### Electric minibus / shuttle

Base purchase cost:

```json
"purchase_price_aud": 96980
```

Rationale:

- The modeled minibus is an 8-passenger electric shuttle/minibus class, not a full-size transit bus.
- Joylong EA6 listings provide an Australian small electric minibus reference.
- The 2026 Joylong EA6 electric minibus listing gives AUD 96,980 excluding government charges.
- A 15-year economic life is used because the Joylong EA6 reference has gross vehicle mass above 3.5 tonnes and fits a bus/minibus category better than a passenger car.

Important caveat:

- The minibus lifetime assumption is consequential. At 15 years, minibus daily fixed cost is close to car daily fixed cost. If an 8-year minibus life were used, daily fixed cost would increase materially. If cost is emphasized in the paper, include a sensitivity or caveat for minibus economic life and battery replacement.

References:

- Trucksales. *2026 Joylong EA6 Electric Minibus*.  
  https://www.trucksales.com.au/showroom/details/2026-joylong-ea6-electric-minibus/SHRM-AD-682006/
- Trucksales. *2023 Joylong EA6 Electric Minibus*.  
  https://www.trucksales.com.au/items/details/2023-joylong-ea6-electric-minibus/OAG-AD-24121295/

---

## 5. Non-energy maintenance cost assumptions

These costs exclude electricity. Electricity is handled separately through `electricity_cost_per_kwh` in the energy model.

| Vehicle class | Maintenance cost (AUD/km) | Interpretation |
|---|---:|---|
| Scooter | 0.06 | Fleet-use allowance for tyres, brakes, bearings, and periodic component replacement. |
| Moped | 0.04 | Light electric two-wheeler allowance for tyres, brakes, drivetrain, and periodic service items. |
| Car | 0.04 | Electric passenger-car non-energy maintenance allowance. |
| Minibus | 0.25 | Conservative small electric minibus allowance, below many full-size transit bus values but above light vehicles. |

Rationale:

- EV maintenance is lower than comparable internal-combustion vehicles due to fewer moving parts, but tyres, brakes, suspension, battery condition checks, alignment, filters, and periodic service items remain relevant.
- The scooter value is higher per kilometre than car/moped because small components wear over relatively low annual distances in intensive micromobility use.
- The minibus value is higher because larger vehicles have heavier tyres, brakes, suspension components, and inspection/maintenance regimes. NREL/FTA electric-bus evaluations report maintenance costs on the order of several tenths of a USD per mile depending on duty cycle, warranty coverage, labour treatment, and parts responsibility.

References:

- Federal Transit Administration. *Procuring and Maintaining Battery Electric Buses and Charging Systems: Best Practices*.  
  https://www.transit.dot.gov/research-innovation/procuring-and-maintaining-battery-electric-buses-and-charging-systems-best
- NREL. *Foothill Transit Battery Electric Bus Demonstration Results*.  
  https://www.nrel.gov/docs/fy17osti/67698.pdf
- NREL. *Battery Electric Bus Evaluations / Zero Emission Bus Evaluation Results*.  
  https://www.nrel.gov/docs/fy19osti/72864.pdf
- NREL. *Zero Emission Bus Evaluation Results*.  
  https://www.nrel.gov/docs/fy23osti/78345.pdf
- Car and Driver. *Maintaining an Electric Car*.  
  https://www.caranddriver.com/shopping-advice/a70535313/maintaining-an-electric-car-ev-how-to/
- Wired. *Everything You Need to Know About Servicing an EV*.  
  https://www.wired.com/story/everything-you-need-to-know-about-servicing-an-ev/

---

## 6. Annualized base-case values

Using `r = 0.07` and `service_days_per_year = 250`:

| Vehicle | Purchase cost (AUD) | Life (yr) | CRF | Annualized capital cost (AUD/yr) | Fixed cost (AUD/service day) | Maintenance (AUD/km) |
|---|---:|---:|---:|---:|---:|---:|
| Scooter | 1,300 | 3 | 0.38105 | 495.37 | 1.98 | 0.06 |
| Moped | 6,000 | 8 | 0.16747 | 1,004.81 | 4.02 | 0.04 |
| Car | 59,648 | 8 | 0.16747 | 9,989.12 | 39.96 | 0.04 |
| Minibus | 96,980 | 15 | 0.10980 | 10,647.88 | 42.59 | 0.25 |

---

## 7. Recommended config update

Update `config/base_config.json` cost model only:

```json
"cost_model": {
  "fixed_cost_per_vehicle": {
    "Scooter": 1.98,
    "Moped": 4.02,
    "Car": 39.96,
    "Minibus": 42.59
  },
  "maintenance_cost_per_km": {
    "Scooter": 0.06,
    "Moped": 0.04,
    "Car": 0.04,
    "Minibus": 0.25
  }
}
```

Do not change `fleet.vehicle_types[].fixed_cost_km_equiv` unless a future experiment explicitly introduces cost into the routing objective.

Optional documentation-only metadata may be stored in this reference file or a separate table, but it is not needed by the current code:

```json
{
  "cost_discount_rate": 0.07,
  "service_days_per_year": 250,
  "cost_currency": "AUD",
  "cost_base_year": 2026,
  "vehicle_capital_assumptions": {
    "Scooter": {"purchase_price_aud": 1300, "economic_life_years": 3},
    "Moped": {"purchase_price_aud": 6000, "economic_life_years": 8},
    "Car": {"purchase_price_aud": 59648, "economic_life_years": 8},
    "Minibus": {"purchase_price_aud": 96980, "economic_life_years": 15}
  }
}
```

---

## 8. Sanity check: all-inclusive private-car running cost

The Australian Taxation Office cents-per-kilometre method gives an all-inclusive car-expense rate of AUD 0.88/km for the 2025--26 year. This rate is **not** used directly in the model because the simulation separates fixed capital cost, non-energy maintenance cost, and electricity cost. It is useful only as a broad reasonableness check for private-car costs.

Reference:

- Australian Taxation Office / official rate references for cents-per-kilometre method.  
  https://softwaredevelopers.ato.gov.au/CentsperKilometreDeductionRateforCarExpenses

---

## 9. Sensitivity options

If cost becomes a central result, the most useful sensitivity checks are:

1. **Minibus economic life sensitivity**: compare the 15-year base case with an 8--10 year minibus life. This is the most important sensitivity because it materially changes minibus daily fixed cost.
2. **Discount-rate sensitivity**: repeat fixed-cost calculations at 3%, 7%, and 10%, following the OIA sensitivity range.
3. **Lower-cost EV car sensitivity**: replace the Tesla Model 3 proxy with a lower-cost Australian EV platform if reviewers question the car capital assumption.
4. **Capital-light sensitivity**: report maintenance + electricity only, excluding daily capital fixed cost.
5. **Autonomy-premium sensitivity**: add a separate scenario for autonomy-stack cost if reliable vehicle-class-specific values become available.

For reference, at alternative discount rates, fixed costs are approximately:

| Vehicle | 3% AUD/day | 7% AUD/day | 10% AUD/day |
|---|---:|---:|---:|
| Scooter | 1.84 | 1.98 | 2.09 |
| Moped | 3.42 | 4.02 | 4.50 |
| Car | 33.99 | 39.96 | 44.72 |
| Minibus | 32.49 | 42.59 | 51.00 |

---

## 10. Suggested manuscript wording

> We report an indicative operating-cost metric computed after routing; it does not influence solver decisions. Vehicle platform capital costs are annualized using a capital recovery factor with a 7\% real discount rate and converted to a per-service-day fixed cost assuming 250 weekday operating days per year. We add non-energy maintenance cost per kilometre and electricity cost from the energy model. The model excludes driver labour, depot and charging infrastructure, insurance, remote supervision, and explicit autonomy-stack premiums, for which consistent vehicle-class-specific Australian data are not available. Cost results should therefore be interpreted as relative operating-cost indicators for comparing fleet compositions rather than as a complete deployment business case.

Suggested table for the paper if space permits:

| Vehicle | Fixed cost (AUD/day) | Maintenance cost (AUD/km) |
|---|---:|---:|
| Scooter | 1.98 | 0.06 |
| Moped | 4.02 | 0.04 |
| Car | 39.96 | 0.04 |
| Minibus | 42.59 | 0.25 |

---

## 11. Notes for future updates

- Keep this file beside `docs/energy_assumptions_reference.md`.
- Update `docs/PROJECT_SPEC.md` after `config/base_config.json` is changed.
- Any future change that makes cost part of the solver objective must be treated as a new modeling assumption and documented separately.
- If final results emphasize cost rankings strongly, include minibus lifetime and lower-cost car sensitivities.
