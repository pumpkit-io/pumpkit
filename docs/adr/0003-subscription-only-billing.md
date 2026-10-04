# Bill only by subscription

Pumpkit charges users only through Stripe subscriptions. The app was imported with a one-off purchase flow: a product catalog, checkout, a refund and dispute lifecycle, grant/revoke hooks, and a section in the billing dialog. Its products were placeholders, and none is planned, so we deleted it rather than maintain about 900 lines of unused, bug-prone lifecycle code. If one-off sales (for example credit packs) become a real need, restore the flow from git history as a new, deliberate decision, and fix its refund-while-disputed transition when you do.
