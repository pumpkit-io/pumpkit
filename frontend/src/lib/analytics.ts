import { captureEvent } from './analyticsConsent';

// track() is typed against these keys, so an event must be declared here to be trackable.
export const EVENTS = {
  // Landing (/)
  landing_nav_logo_clicked: { description: 'Landing: clicked the logo in the header.' },
  landing_nav_authors_clicked: {
    description: 'Landing: clicked the "Authors" header link. Props: surface (desktop | mobile).',
  },
  landing_nav_pricing_clicked: {
    description: 'Landing: clicked the "Pricing" header link. Props: surface (desktop | mobile).',
  },
  landing_nav_get_started_clicked: {
    description:
      'Landing: clicked the "Get started" header button. Props: surface (desktop | mobile).',
  },
  landing_mobile_menu_opened: { description: 'Landing: opened the mobile header menu.' },
  landing_mobile_menu_closed: { description: 'Landing: closed the mobile header menu.' },
  landing_hero_cta_clicked: { description: 'Landing: clicked the "Start writing" hero button.' },
  landing_hero_screenshot_viewed: {
    description: 'Landing: the hero screenshot first scrolled into view.',
  },
  landing_authors_section_viewed: {
    description: 'Landing: the authors section first scrolled into view.',
  },
  landing_pricing_section_viewed: {
    description: 'Landing: the pricing section scrolled into view.',
  },
  landing_pricing_plan_viewed: {
    description: "Landing: a Plan's pricing table first scrolled into view. Props: plan_key.",
  },
  landing_pricing_cta_clicked: {
    description: 'Landing: clicked the "Get started" button at the end of the pricing section.',
  },

  // Login (/login) + auth callbacks
  login_google_clicked: { description: 'Login: clicked "Continue with Google".' },
  login_google_succeeded: {
    description: 'Login: Google OAuth callback completed and a session was created.',
  },
  login_google_failed: {
    description: 'Login: Google OAuth callback failed (no access token / error returned).',
  },
  login_magic_link_submitted: { description: 'Login: submitted the magic-link request form.' },
  login_magic_link_requested_succeeded: {
    description: 'Login: backend accepted the magic-link request.',
  },
  login_magic_link_requested_failed: {
    description: 'Login: backend rejected the magic-link request.',
  },
  login_magic_link_invalid_shown: {
    description: 'Login: the "link is invalid or has expired" banner was shown.',
  },
  login_magic_link_callback_succeeded: {
    description: 'Login: magic-link callback validated and a session was created.',
  },
  login_magic_link_callback_failed: {
    description: 'Login: magic-link callback failed (link invalid/expired).',
  },

  // App shell
  sidebar_new_post_clicked: {
    description: 'New post from the sidebar or the shortcut. Props: source (sidebar | shortcut).',
  },
  sidebar_mobile_drawer_opened: { description: 'Mobile sidebar: opened the drawer.' },
  sidebar_mobile_drawer_closed: {
    description: 'Mobile sidebar: closed the drawer. Props: via_backdrop.',
  },

  // Settings (/settings)
  settings_theme_changed: {
    description: 'Settings: changed the theme in Appearance. Props: theme (system/light/dark).',
  },
  settings_sign_out_clicked: { description: 'Settings: clicked "Sign out" in the header.' },
  account_profile_saved: { description: 'Account: saved profile changes. Props: fields_changed.' },
  account_profile_save_failed: {
    description: 'Account: profile save failed. Props: error_message.',
  },

  billing_choose_plan_opened: {
    description: 'Billing: a prompt to subscribe sent the User to Choose a Plan. Props: source.',
  },
  billing_subscription_checkout_started: {
    description: 'Billing: started a Subscription checkout. Props: plan_key.',
  },
  billing_checkout_redirect_failed: {
    description: 'Billing: could not redirect to Stripe. Props: error_message.',
  },
  billing_checkout_succeeded: {
    description: 'Billing: returned from Stripe via the success URL.',
  },
  billing_checkout_cancelled: {
    description: 'Billing: returned from Stripe via the cancel URL.',
  },
  billing_portal_opened: { description: 'Billing: opened the Stripe billing portal.' },

  // Home: writing
  inspiration_author_added: {
    description: 'Home: added an Inspiration author and its posts were fetched.',
  },
  inspiration_author_removed: { description: 'Home: removed an Inspiration author.' },
  inspiration_authors_refreshed: {
    description: 'Home: refreshed an Inspiration author and its latest posts were fetched.',
  },
  post_version_requested: {
    description: 'Home: asked for a Version of a Post. Props: kind (brief | feedback).',
  },
  post_version_failed: {
    description: 'Home: writing a Version failed. Props: kind (brief | feedback).',
  },
  post_final_copied: {
    description: 'Post page: copied the text on screen with Copy post, every Part of it.',
  },

  // Scheduled (/scheduled) + the X callback
  x_connected: { description: 'Settings: connected an X account through X consent screen.' },
  x_disconnected: { description: 'Settings: disconnected the X account.' },
  community_looked_up: {
    description:
      'Scheduled: looked up a Community pasted by its URL or ID. Props: found (boolean), named (boolean, only when found).',
  },
  scheduled_post_created: {
    description:
      'Scheduled: created a Scheduled post. Props: format (post | thread), part_count (number), source (typed | final), post_now (boolean), destination (profile | community), share_with_followers (boolean, only for a Community).',
  },
  // Tracked by the backend, which alone sees the outcome; listed here to keep one catalog.
  scheduled_post_published: {
    description:
      'Scheduled: X published every Part of a Scheduled post. Props: format (post | thread), part_count (number), source (typed | final), destination (profile | community), share_with_followers (boolean, only for a Community).',
  },
  scheduled_post_failed: {
    description:
      'Scheduled: a Scheduled post Failed. Props: format (post | thread), part_count (number), reason (not_subscribed | x_account_changed | reconnect_needed | x_unavailable | refused_by_x | outcome_unknown).',
  },
} as const satisfies Record<string, { description: string }>;

export type EventName = keyof typeof EVENTS;

export function track<E extends EventName>(event: E, properties?: Record<string, unknown>): void {
  captureEvent(event, properties);
}
