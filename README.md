# AtlListSpacesDC

List Jira Data Center projects or Confluence Data Center spaces and export the results to CSV.

## Description

This utility targets Atlassian Data Center deployments and exports a summary of either Jira projects or Confluence spaces. It authenticates with a personal access token (PAT) using bearer auth and writes a CSV file with the key metadata columns for each item.

The script is built for command-line use and includes validation for required arguments, automatic output filenames, and optional verbose progress reporting.

## Options

| Option | Short | Required | Description |
| --- | --- | --- | --- |
| --type | -t | Yes | Item type: `jira` or `confluence` |
| --site | -s | Yes | Data Center base URL, such as `https://jira.example.com` |
| --token | -p | Yes | PAT used as the bearer token |
| --out | -f | No | Output CSV path. If omitted, a timestamped filename is generated automatically |
| --verbose | -v | No | Print per-item timing and extra progress information while the script runs |

## Default Output Naming

When `--out` is not supplied, the script creates a filename in this pattern:

```text
list_spaces_dc_<type>_<hostname>_<UTC timestamp>.csv
```

Example:

```text
list_spaces_dc_jira_jira_example_com_20260824T151123Z.csv
```

## Usage Examples

```bash
python AtlListSpacesDC.py -t jira --site https://jira.example.com --token YOUR_PAT
python AtlListSpacesDC.py -t confluence --site https://confluence.example.com --token YOUR_PAT --out ./spaces.csv
python AtlListSpacesDC.py -t jira --site https://jira.example.com --token YOUR_PAT --verbose
```

## CSV Output

The generated CSV includes these columns:

- Space Name
- Space Key
- Creation Date
- Last Activity Date
- Number of Items
- Status
- Admins
- Business Owner

Notes:

- For Jira, the script enumerates projects and uses the oldest issue creation date as a proxy for project creation when the project metadata does not provide a direct date.
- For Confluence, the script enumerates spaces and derives metadata such as creation date from space/homepage history when available.
- The script skips personal Confluence spaces, and admin names are flattened into a single comma-separated field.

## Behavior and Notes

- Required arguments are not optional; missing values exit with code 1 and print a clear error.
- The site URL must include a protocol such as `http://` or `https://`.
- The script accepts only the `jira` and `confluence` values for `--type`.
- Console output includes colored status lines in green, red, yellow, and cyan as the script runs.
- No environment-variable fallback is used for `--site` or `--token`.
