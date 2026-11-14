"""Turn a stream of trade reports into one row per real trade.

A raw file is a log of messages, not a list of trades. A trade appears as a
NEWT (new) report. Later a CORR report can replace it, or an EROR report can
cancel it; each points back through "Original Dissemination Identifier".
Other reports (amendments, terminations, novations, compressions, exercises)
are events on existing positions and carry no fresh market price.
"""

from __future__ import annotations

import pandas as pd

ID = "Dissemination Identifier"
ORIG = "Original Dissemination Identifier"
ACTION = "Action type"
EVENT = "Event type"
STAMP = "Event timestamp"


def apply_lifecycle(raw: pd.DataFrame) -> pd.DataFrame:
    """Return price-forming trades after applying corrections and cancellations.

    ``raw`` may hold one day or many; a correction that arrives days after the
    trade is applied as long as both rows are present.
    Adds: trade_id (id of the first report), n_corrections.
    """
    raw = raw.reset_index(drop=True)
    cancelled = set(raw.loc[raw[ACTION] == "EROR", ORIG])

    # Latest correction for each id it replaces.
    corr = raw[raw[ACTION] == "CORR"].sort_values(STAMP)
    replaced_by = dict(zip(corr[ORIG], corr.index, strict=True))  # later rows overwrite earlier ones
    row_id = raw[ID].to_dict()

    base = raw[(raw[ACTION] == "NEWT") & (raw[EVENT] == "TRAD")]
    keep_rows, trade_ids, n_corr = [], [], []
    for idx, first_id in zip(base.index, base[ID], strict=True):
        cur_idx, cur_id, hops, dead = idx, first_id, 0, False
        while True:
            if cur_id in cancelled:
                dead = True
                break
            nxt = replaced_by.get(cur_id)
            if nxt is None or hops > 50:
                break
            cur_idx, cur_id, hops = nxt, row_id[nxt], hops + 1
        if not dead:
            keep_rows.append(cur_idx)
            trade_ids.append(first_id)
            n_corr.append(hops)

    out = raw.loc[keep_rows].copy()
    out["trade_id"] = trade_ids
    out["n_corrections"] = n_corr
    out = out.reset_index(drop=True)
    # Counts for the data report: where every raw report went.
    out.attrs["lifecycle"] = {
        "reports": int(len(raw)),
        "new_trade_reports": int(len(base)),
        "cancelled": int(len(base) - len(keep_rows)),
        "corrected": int(sum(n > 0 for n in n_corr)),
        "not_price_forming": int(len(raw) - len(base) - (raw[ACTION].isin(["CORR", "EROR"])).sum()),
        "trades": int(len(out)),
    }
    return out
