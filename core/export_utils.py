def dataframe_to_markdown(df):
    """Convert a dataframe-like object to a Markdown table without optional tabulate."""
    headers = list(df.columns)
    rows = []
    for _, row in df.iterrows():
        cells = []
        for header in headers:
            value = str(row[header]).replace("|", "\\|").replace("\n", "<br>")
            cells.append(value)
        rows.append(f"| {' | '.join(cells)} |")

    return "\n".join([
        f"| {' | '.join(headers)} |",
        f"| {' | '.join(['---'] * len(headers))} |",
        *rows,
    ])
