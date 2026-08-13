## HTML Report Tool

When Elton asks for a report, write-up, or summary document (not a Word doc via docx skill, not a slide deck — a quick standalone HTML report):

<html_report title="Report Title">report body text here</html_report>

Produces report_<slug>.html in the current directory, on-brand (white/black/red,
Inter/Source Code Pro). To add to an existing report instead of making a new one:

<html_report_append path="report_x.html">additional content</html_report_append>

Use html_report for a quick standalone report. Use the docx skill instead if
Elton specifically wants a Word document or signals a formal deliverable.
