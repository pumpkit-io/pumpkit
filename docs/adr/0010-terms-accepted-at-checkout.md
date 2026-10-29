# Users accept the Terms at checkout, not at sign-in

A User accepts the Terms in the Billing dialog, before every Stripe Checkout, by ticking separate boxes, so each new Subscription has its own acceptance. Pumpkit records the Terms version and the time. Sign-in only shows a notice linking to the Terms and the Privacy Policy, because the Google button leaves no room for checkboxes, and signing in creates the account. Every product feature needs a Subscription, so no User reaches the product without accepting. Checkout acceptance also has to collect two things a single "I agree" cannot give: a consumer's request for immediate performance, which waives the 14-day withdrawal right, and a business's specific approval of onerous clauses (liability limits, court venue, suspension and termination, automatic renewal), which arts. 1341 and 1342 of the Italian Civil Code require for those clauses to bind it. Moving acceptance to sign-up would lose that evidence.

ADR 0011 narrows this: the Terms are accepted at checkout only on an Instance that sells Plans and has Operator details.

The web app redesign (#164) removed the Billing dialog: the boxes now sit in the Choose a Plan card on Settings, still before every Stripe Checkout. The decision is unchanged.
