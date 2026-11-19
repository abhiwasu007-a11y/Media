"""Knowledge-library source rules (owner decision D12; CCR-270, CCR-285 PROPOSED).

Four parts, all pure or read-only: the per-work copyright record and the computed public-domain
flag (``copyright``), the read-only reader of the private library checkout (``reader``), exact
quote verification with the fake-quote guard (``quotes``), and the credit lines / further-reading
check (``credits``). The public repository holds code and synthetic tests only; library text is
read at run time and never stored, logged or copied.
"""
