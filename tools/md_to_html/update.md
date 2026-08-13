
# MD_TO_HTML CLI TOOL UPDATE 

1. BY DEFAULT I ONLY WANTETO CONVERT TO UNSTYLED RAW HTML, WRAPPED IN ARTICLE TAGS, MAKING A TRUE HTML DOCUMENT with no style or header.

2. EQUIVALENT CONVERSION 

- WHEN FORMATTING SETTINGS ARE ENABLED IT NEEDS TO DO A MUCH BETTER JOB OF ACTUALLY IDENTIFYING MARKDOWN AND CONVERTING IT TO THE CORRECT HTML EQUIVALENT TAGS 

- RIGHT NOW IT'S TAKING JSON THAT'S CORRECTLY WRAPPED IN MARKDOWN JSON TAGS AND PUTTING IT INTO A PARAGRAPH TAG IN HTML RATHER THAN A CODE BOX OR SOMETHING...

- IT NEEDS SEVERELY OVERHAULED 

3. --STYLE Should enable default built-in style and full html page output (including headers) from a built in template, but by default will be unstyled but correctly formatted with the appropriate tags matching the markdown converted documents marked down equivalent tags 


-----


# ORIGINAL INTENDED DESIGN PROMPT:

I need a simple sleek white document template that is Aria compliant that has built in meta, SEO and open graph support. 

Should be all white, Black font, #DE2626 headers, links and bold/emphasis.
He must be footed with my contact information on the page body and links to my github and my website.

Inter, roboto mono sans font.

The template must have an H1 space for the tile, embedded CSS for headers, and various formatting to make it look professional. It must use an article tag.


----------------------

I need a CLI tool that will include the document template built into it. It will let me target a file or a folder, If I talk at a file it will create a new folder in the files directory or if I target it directory it will create the new folder in that directory. The folder name will be MD_TO_HTML.

I need it to do offline conversion of markdown files to HTML that maintains formatting so that it will be stylized by the template and use the templates embedded CSS. 


If I don't get a file it'll convert that file If I target a directory it will convert all Mark down files in that directory.

All the converted files will go into the new directory that's created, MD_TO_HTML.

Everything should be embedded in the article space of the template.