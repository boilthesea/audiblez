import os
import zipfile
import json
from bs4 import BeautifulSoup, NavigableString
from pathlib import Path
from types import SimpleNamespace

def get_pre_parse_stats(book_path):
    """
    Calculates the raw character count of all document items in the epub.
    """
    total_raw_chars = 0
    section_stats = {}
    
    try:
        with zipfile.ZipFile(book_path, 'r') as z:
            for name in z.namelist():
                if name.lower().endswith(('.html', '.xhtml', '.htm')):
                    content = z.read(name).decode('utf-8', errors='ignore')
                    raw_len = len(content)
                    total_raw_chars += raw_len
                    section_stats[name] = raw_len
    except Exception as e:
        print(f"Error calculating pre-parse stats: {e}")
        
    return total_raw_chars, section_stats

def create_skeleton(html_content, max_snippet=50):
    """
    Strips large text blocks from HTML while preserving tags and attributes.
    """
    soup = BeautifulSoup(html_content, 'lxml')
    
    for element in soup.find_all(string=True):
        if isinstance(element, NavigableString):
            text = element.strip()
            if not text:
                continue
            
            length = len(text)
            if length > max_snippet:
                snippet = text[:max_snippet] + "..."
                element.replace_with(f'[Snippet: "{snippet}"] ({length} chars)')
            else:
                element.replace_with(f'[Snippet: "{text}"] ({length} chars)')
                
    return str(soup)

def generate_report(metadata, sections, output_path):
    """
    Generates a self-contained HTML report.
    """
    html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>Ebook Skeleton Report - {title}</title>
    <style>
        body {{ font-family: sans-serif; line-height: 1.6; color: #333; max-width: 1200px; margin: 0 auto; padding: 20px; background: #f4f4f9; }}
        h1, h2 {{ color: #2c3e50; }}
        .dashboard {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin-bottom: 30px; }}
        .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .card h3 {{ margin-top: 0; font-size: 0.9em; text-transform: uppercase; color: #7f8c8d; }}
        .card .value {{ font-size: 1.5em; font-weight: bold; }}
        .anomaly {{ color: #e74c3c; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; background: white; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #ecf0f1; }}
        tr:hover {{ background-color: #f9f9f9; }}
        pre {{ background: #2c3e50; color: #ecf0f1; padding: 15px; border-radius: 5px; overflow-x: auto; font-size: 0.9em; }}
        .skeleton-section {{ margin-bottom: 40px; }}
        details {{ background: white; padding: 10px; border-radius: 5px; margin-bottom: 10px; border: 1px solid #ddd; }}
        summary {{ font-weight: bold; cursor: pointer; padding: 5px; }}
    </style>
</head>
<body>
    <h1>Ebook Structural Analysis</h1>
    <div class="dashboard">
        <div class="card">
            <h3>Title</h3>
            <div class="value">{title}</div>
        </div>
        <div class="card">
            <h3>Author</h3>
            <div class="value">{author}</div>
        </div>
        <div class="card">
            <h3>Overall Ratio (Post/Pre)</h3>
            <div class="value {ratio_class}">{ratio:.2f}</div>
        </div>
        <div class="card">
            <h3>Total Chars (Extracted)</h3>
            <div class="value">{total_post}</div>
        </div>
    </div>

    <h2>Section Breakdown</h2>
    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Section Title</th>
                <th>Source File</th>
                <th>Pre-parse (Raw Chars)</th>
                <th>Post-parse (Text Chars)</th>
                <th>Ratio</th>
                <th>Status</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>

    <h2>Structural Skeletons</h2>
    {skeletons}

    <script>
        // Simple interactions can be added here
    </script>
</body>
</html>
"""
    
    table_rows = ""
    skeletons = ""
    total_pre = 0
    total_post = 0
    
    for i, s in enumerate(sections, 1):
        pre = s.get('pre_chars', 0)
        post = s.get('post_chars', 0)
        total_pre += pre
        total_post += post
        ratio = post / pre if pre > 0 else 0
        
        status = "OK"
        status_class = ""
        if ratio > 1.2:
            status = "⚠️ Duplication?"
            status_class = "anomaly"
        elif post == 0:
            status = "Empty"
            
        table_rows += f"""
            <tr>
                <td>{i}</td>
                <td>{s.get('title', 'N/A')}</td>
                <td><code>{s.get('src', 'N/A')}</code></td>
                <td>{pre:,}</td>
                <td>{post:,}</td>
                <td>{ratio:.2f}</td>
                <td class="{status_class}">{status}</td>
            </tr>
        """
        
        skeletons += f"""
            <div class="skeleton-section">
                <details>
                    <summary>Section {i}: {s.get('title')} ({s.get('src')})</summary>
                    <pre><code>{BeautifulSoup(s.get('skeleton', ''), 'lxml').prettify().replace('<', '&lt;').replace('>', '&gt;')}</code></pre>
                </details>
            </div>
        """

    overall_ratio = total_post / total_pre if total_pre > 0 else 0
    ratio_class = "anomaly" if overall_ratio > 1.2 else ""
    
    report_html = html_template.format(
        title=metadata.get('title', 'Unknown'),
        author=metadata.get('creator', metadata.get('author', 'Unknown')),
        ratio=overall_ratio,
        ratio_class=ratio_class,
        total_post=f"{total_post:,}",
        table_rows=table_rows,
        skeletons=skeletons
    )
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(report_html)

if __name__ == "__main__":
    # Test stub
    pass
