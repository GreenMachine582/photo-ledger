-- v1.1: who made a decision. 'you' on the review page, or 'auto' when a rule on the Settings page
-- decided an obvious pair at match: exact copies told apart only by path or source priority, or a
-- name conflict between pictures that don't look alike. `rule` names the rule. A closure carries
-- the values of the decision that caused it. Existing rows were all made by hand.

ALTER TABLE decisions ADD COLUMN decided_by TEXT NOT NULL DEFAULT 'you'
    CHECK (decided_by IN ('you', 'auto'));
ALTER TABLE decisions ADD COLUMN rule TEXT
    CHECK (rule IS NULL OR rule IN ('tidier_path', 'priority', 'unlike_names'));
