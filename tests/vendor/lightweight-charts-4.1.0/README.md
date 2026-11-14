# TradingView Lightweight Charts 4.1.0 (test copy)

The chart library the instrument page loads from
`https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js`,
copied unmodified from the npm package `lightweight-charts@4.1.0`
(tarball integrity `sha512-O7RPoRLPPmwRNOTmBq1ne5eKgjdVZocd2TE77JCfaVJEwS+0meN9UwMKGNGiiRQBb2UkuhyBSiX7XrErBuL+CQ==`,
shasum `c03e64621e4d9ff6eb0eb93db2fd41e241dcb139`), with its licence (`LICENSE`,
Apache License 2.0). Copyright (c) 2023 TradingView, Inc.

Only the measured tests read it (`tests/test_instrument_desk_v2.py`): they lay the
page out in a headless Chromium with every network URL blocked, so the library is
put on the page from here instead of the CDN. The page itself still loads it from
the CDN, with the subresource-integrity hash of this exact file.
