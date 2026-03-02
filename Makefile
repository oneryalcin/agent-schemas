SCHEMA    := claude-code/v2.1.59/session.schema.json
OUTDIR    := generated

# datamodel-codegen chokes on $id URLs — strip it for local generation
SCHEMA_NOID := $(OUTDIR)/.session_noid.schema.json

.PHONY: all clean python typescript go rust validate

all: python typescript

$(OUTDIR):
	mkdir -p $(OUTDIR)

$(SCHEMA_NOID): $(SCHEMA) | $(OUTDIR)
	python3 -c "import json; s=json.load(open('$(SCHEMA)')); s.pop('\$$id',None); json.dump(s,open('$@','w'))"

# --- Python (Pydantic v2) ---
python: $(OUTDIR)/claude_code_types.py

$(OUTDIR)/claude_code_types.py: $(SCHEMA_NOID)
	uv run --with datamodel-code-generator datamodel-codegen \
		--input $(SCHEMA_NOID) \
		--output $@ \
		--output-model-type pydantic_v2.BaseModel
	@echo "Generated $@"

# --- TypeScript ---
typescript: $(OUTDIR)/claude_code_types.d.ts

$(OUTDIR)/claude_code_types.d.ts: $(SCHEMA) | $(OUTDIR)
	npx json-schema-to-typescript $(SCHEMA) -o $@
	@echo "Generated $@"

# --- Go (via quicktype) ---
go: $(OUTDIR)/claude_code_types.go

$(OUTDIR)/claude_code_types.go: $(SCHEMA) | $(OUTDIR)
	npx quicktype --src $(SCHEMA) --src-lang schema --lang go --package agentschemas -o $@
	@echo "Generated $@"

# --- Rust (via quicktype) ---
rust: $(OUTDIR)/claude_code_types.rs

$(OUTDIR)/claude_code_types.rs: $(SCHEMA) | $(OUTDIR)
	npx quicktype --src $(SCHEMA) --src-lang schema --lang rust -o $@
	@echo "Generated $@"

# --- Validate ---
validate:
	python3 claude-code/validate.py ~/.claude/projects/

clean:
	rm -rf $(OUTDIR)
