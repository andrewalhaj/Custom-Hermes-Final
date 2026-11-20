-- A machine's login is named as the machine, so it saves facts only under its own name, as it already
-- records events (ARCHITECTURE.md section 4.2: `source` is the machine that wrote the row; issue #25).
-- Works with the code deployed before it: nothing in this repository writes facts yet (rule C10).

alter policy facts_agent_insert on memory.facts with check (source = current_user);

update memory.schema_level set level = 2;
