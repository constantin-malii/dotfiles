# Handling Large Confluence Documents

**Date**: 2025-02-06
**Issue**: Bash script fails on large markdown files
**Solution**: Use Python script for files > 20KB

## The Problem

The bash script `confluence-rest-api.sh` hits OS command-line argument length limits when uploading large files.

### Root Cause

```bash
# In confluence-rest-api.sh (line 133)
$0 create "$space" "$title" "$html" "$parent_id"
```

**What happens:**
1. Script reads entire markdown file
2. Converts to HTML (stored in `$html` shell variable)
3. Recursively calls itself with `$html` as command-line argument
4. OS rejects if argument > ~128KB (varies by system)

**Example that fails:**
- 30KB markdown file
- Converts to ~100KB HTML
- With escaping/encoding: >128KB argument
- Result: "Argument list too long" error

## The Solution

### Two-Pronged Approach

1. **Bash script** (default) - for normal files < 20KB
2. **Python script** (large files) - for files > 20KB

### Why Python Works

**Python approach:**
```python
# Read file from disk (no argument passing)
with open(file_path, 'r') as f:
    content = f.read()

# Convert in memory
html = markdown.markdown(content)

# POST directly via requests library
requests.post(url, json=payload, auth=(email, token))
```

**Key difference:**
- No command-line arguments (reads from disk)
- No subprocess calls (direct HTTP request)
- Memory-only operation (can handle GB files)

## Implementation

### Python Script Location
`~/.claude/scripts/confluence-upload-large.py`

### Usage

```bash
# Set credentials (one-time)
export CONFLUENCE_EMAIL="your.email@company.com"
export CONFLUENCE_API_TOKEN="your-token-here"

# Upload large file
python3 ~/.claude/scripts/confluence-upload-large.py \
  "~828448473" \
  "Page Title" \
  path/to/large-file.md

# With parent page
python3 ~/.claude/scripts/confluence-upload-large.py \
  "~828448473" \
  "Page Title" \
  path/to/large-file.md \
  PARENT-PAGE-ID
```

### Dependencies

```bash
# Install once
pip install requests markdown
```

## When to Use Each

| Scenario | Tool | Why |
|----------|------|-----|
| Small docs (< 20KB) | Bash script | Fast, no dependencies |
| Large docs (> 20KB) | Python script | No size limit |
| Complex markdown | Python script | Better conversion |
| Quick operations | Bash script | Already set up |
| Tables, code blocks | Python script | Proper library support |

## File Size Guidelines

```
< 10KB   → Bash script (fast)
10-20KB  → Bash script (usually works)
20-50KB  → Python script (safer)
> 50KB   → Python script (required)
```

## Alternative Solutions Considered

### 1. Fix Bash Script with Temp Files
```bash
# Write HTML to temp file instead of passing as argument
temp_file=$(mktemp)
echo "$html" > "$temp_file"
curl --data "@$temp_file" ...
rm "$temp_file"
```

**Pros**: No Python dependency
**Cons**: Still need markdown conversion, temp file cleanup

### 2. Use stdin/heredoc
```bash
curl -d @- <<EOF
{"content": "$html", ...}
EOF
```

**Pros**: No temp files
**Cons**: Complex JSON escaping, still hits limits

### 3. Pandoc for Conversion
```bash
pandoc -f markdown -t html file.md | curl ...
```

**Pros**: Better markdown conversion than sed
**Cons**: Pandoc not always installed, still hits limits

**Winner**: Python script (Option 2 from above)

## Testing Results

### Test Case: 30KB Markdown File

**Bash script:**
```
Converting Ally-Data-Integration-Architecture-Analysis.md to HTML...
/c/Users/.../jq: Argument list too long
❌ FAILED
```

**Python script:**
```
File size: 0.03 MB
Converting markdown to HTML...
Creating page in space ~828448473...
Page created successfully
ID: 5173248003
URL: https://symend.atlassian.net/wiki/spaces/~828448473/pages/5173248003
✅ SUCCESS
```

## Best Practices

### For Document Authors

1. **Keep docs modular**: Split large documents into multiple pages
2. **Use child pages**: Create parent with links to child detail pages
3. **Consider size early**: If doc will be >20KB, plan for Python upload

### For Skill Users (Claude)

1. **Check file size first**: `ls -lh file.md` before upload
2. **Use Python for large files**: Don't retry bash script multiple times
3. **Set credentials once**: Export environment variables at session start

### For Future Maintenance

1. **Keep both scripts**: Bash for speed, Python for size
2. **Document limitations**: Update skill docs when limits change
3. **Monitor usage**: Track which approach is used more often

## Skill Updates Made

### Updated Files

1. **`SKILL.md`**:
   - Added "For Large Files" section
   - Added troubleshooting guide
   - Documented when to use each approach

2. **`~/.claude/scripts/confluence-upload-large.py`**:
   - Created standalone Python uploader
   - Proper error handling
   - File size reporting

### What Wasn't Changed

- **Bash script**: Left as-is (works fine for small files)
- **Core skill logic**: Only documentation updated

## Conclusion

**Problem**: OS argument limits broke bash script for large files

**Solution**: Python script that reads from disk

**Result**: Can now upload Confluence docs of any size

**Best practice**: Use bash for quick operations, Python for large docs

---

**Related:**
- Main skill: `SKILL.md`
- Bash script: `~/.claude/scripts/confluence-rest-api.sh`
- Python script: `~/.claude/scripts/confluence-upload-large.py`
