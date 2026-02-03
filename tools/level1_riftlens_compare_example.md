# Exemple de comparaison RiftLens

Prev: example.csv
Curr: example_drift.csv

Seuil 0.10: prev=6 edges, curr=6 edges
  c-t: -0.200000 -> -0.848235 (d=-0.648235)
  a-c: -0.900000 -> -0.583161 (d=+0.316839)
  b-c: -0.739795 -> -0.910127 (d=-0.170331)

Seuil 0.30: prev=5 edges, curr=6 edges
  Nouvelles: c-t
  a-c: -0.900000 -> -0.583161 (d=+0.316839)
  b-c: -0.739795 -> -0.910127 (d=-0.170331)
  a-b: 0.904194 -> 0.849668 (d=-0.054526)

Seuil 0.50: prev=5 edges, curr=6 edges
  Nouvelles: c-t
  a-c: -0.900000 -> -0.583161 (d=+0.316839)
  b-c: -0.739795 -> -0.910127 (d=-0.170331)
  a-b: 0.904194 -> 0.849668 (d=-0.054526)

Seuil 0.70: prev=4 edges, curr=4 edges
  Disparues: a-c
  Nouvelles: c-t
  b-c: -0.739795 -> -0.910127 (d=-0.170331)
  a-b: 0.904194 -> 0.849668 (d=-0.054526)
  b-t: 0.739795 -> 0.792601 (d=+0.052806)

Seuil 0.90: prev=2 edges, curr=1 edges
  Disparues: a-b, a-c
  Nouvelles: b-c

Seuil 0.95: prev=0 edges, curr=0 edges
