Schema v1 is defined by the SQLAlchemy models and created at startup via Base.metadata.create_all. For this local small application no destructive migration is run. Back up named db-data before modifying schemas.

v1.1 adds pre-registered sequential group-sequential testing:
- sequential_plans: locked per-look dual-group cumulative reach thresholds and per-look alpha allocations; alpha stored as integer millionths (alpha_total/alpha_spent) so repeated spend cannot drift past the study cap.
- sequential_unblindings: unique (plan_id, stage); one immutable data version per look, test result and alpha deduction committed together.
- sequential_corrections: diagnostic recomputes only; original conclusions and spent alpha are never reverted.
create_all only creates missing tables and never alters existing ones, so an existing v1 database upgrades in place; a fresh volume creates the full schema at once.
