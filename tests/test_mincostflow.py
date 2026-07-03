"""Tests for the min-cost flow core.

Two of these use small graphs whose optimum was worked out by hand, so a
regression in the algorithm shows up as a concrete wrong number rather than a
vague property failure. The rest assert the structural invariants any correct
flow must satisfy.
"""

from src.mincostflow import MinCostFlow