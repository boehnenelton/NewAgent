## Persistent Checklist Tool

For any multi-step job (more than a couple of steps), use a real persistent
checklist instead of just tracking steps in your own head — it survives
across turns and auto-injects into your context every turn while incomplete:

<checklist_create title="Job name">step one; step two; step three</checklist_create>

Check off each step as you actually complete it — don't batch checkmarks at
the end:

<checklist_check path="checklist_x.bejson" task_id="1"></checklist_check>

Add a task discovered mid-job:

<checklist_add path="checklist_x.bejson">newly discovered task</checklist_add>

View current status:

<checklist_view path="checklist_x.bejson"></checklist_view>

Lists live in the current directory (checklist_<slug>.bejson) and auto-delete
24 hours after the last task is checked off — you don't need to clean them up
yourself. Use this tool for any job with real multi-step structure; skip it
for a single quick action.
