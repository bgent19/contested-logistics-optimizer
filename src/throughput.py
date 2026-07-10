"""Network-level throughput analysis: maximum resupply rate and its witness cut.

Wraps the Edmonds-Karp core for a `Network` by adding a super-source over all
supply nodes and a super-sink over all demand nodes, then reports the answer in
domain terms: how many units per planning window the theater can absorb, and the
minimum-capacity set of lanes whose loss caps it (the adversary's cheapest
capacity-weighted blockade -- the Day 3 certificate).

Terminal arcs (super-source -> supply, demand -> super-sink) are given large
capacity so the cut is always expressed in *lanes*, not in "a hub simply doesn't
hold enough." Throughput is therefore the capacity ceiling of the lane network,
which is exactly the quantity interdiction tries to drive down.
"""