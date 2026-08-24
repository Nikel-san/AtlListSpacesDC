# AtlListSpacesDC

List Jira Data Center projects or Confluence Data Center spaces and export the results to CSV.

## Description

This utility mirrors the Cloud version of AtlListSpaces but targets Atlassian Data Center deployments. It uses a PAT for bearer authentication and requires all parameters to be supplied on the command line. The script supports both Jira and Confluence listing modes and writes the output to a CSV file with the required metadata columns.

## Options

| Option | Short | Required | Description |
| --- | --- | --- | --- |
| --type | -t | Yes | Item type: `jira` or `confluence` |
| --site | -s | Yes | Data Center base URL, such as `https://jira.example.com` |
| --token | -p | Yes | Personal Access Token used as a bearer token |
| --out | -f | No | Output CSV path; defaults to a generated filename |

## Usage Examples

```bash
python AtlListSpacesDC.py -t jira --site https://jira.example.com --token YOUR_PAT
python AtlListSpacesDC.py -t confluence --site https://confluence.example.com --token YOUR_PAT --out ./spaces.csv
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

## Notes

- No environment variable fallback is used for `--site` or `--token`.
- Missing required arguments exit with code 1 and print a clear error message.
- Console output uses colored status messages in GREEN, RED, YELLOW, and CYAN.
