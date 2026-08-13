## Project Tracker (.bejson_project.json)

Every one of Elton's projects has a .bejson_project.json at its root — this
is THE project tracker / changelog. Schema: Version, Change_Notes/Notes,
Date_YYYY-MM-DD, Time (exact field names vary slightly per project; read the
file's Fields list before writing to it by hand).

To add a properly-formatted entry without hand-writing JSON:

<project_log version="v1.2.3">what changed and why</project_log>

This walks up from the current directory to find .bejson_project.json, so it
works from any subdirectory of the project, not just the root. Use this any
time you finish real work on a versioned project and Elton's own policy
requires a changelog entry (which is essentially always — see his Mandatory
Change Log Requirement).
