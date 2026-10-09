# VoltPilot: Neon database with a preloaded Store & POS but empty analytics

This patch is the intended compromise for the VoltPilot demo:

- On a **brand-new hosted PostgreSQL database only**, create the familiar four store locations, existing starter product catalogue (13 SKUs, including laptops, headphones, monitors, TVs and accessories), and per-store opening stock quantities used by the current Store & POS experience.
- Those opening-stock quantities and catalog prices are starter values carried from the existing local Store & POS experience. They keep the Store page usable immediately, but the retailer should confirm/edit them to match actual opening counts and prices before operational use.
- Do **not** create synthetic sales history, POS transactions, imported observations, supplier records/offers, promotions, purchase orders, forecast models, historical recommendations, or historical audit events.
- On local SQLite, retain the existing local demo behaviour so development is not unexpectedly changed.
- Once real sales/records are entered, the current backend transaction flows recalculate the agent based on those records. Areas requiring historical sales, supplier or PO data must show an honest no-data state until the records are provided.

## Safe application
1. Keep a backup of project source and do not delete local SQLite.
2. Extract this patch into the project root, replacing only included files.
3. Check `python -c "from app.main import app; print('IMPORT OK')"` and run tests locally.
4. Commit and push the included changes before setting `DATABASE_URL` on Render.
5. Configure `DATABASE_URL` in Render only after the updated code has deployed.

The patch does not transfer old SQLite data to Neon. It initializes only starter store/catalog/opening stock on the *first start* of a completely empty PostgreSQL database. It does not overwrite a database that already has stores or products.
