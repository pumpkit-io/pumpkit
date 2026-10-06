import { posthog } from './posthog';

const enabled = import.meta.env.VITE_POSTHOG_ENABLED === 'true';

// track() is typed against these keys, so an event must be declared here to be trackable.
export const EVENTS = {
  // Landing (/)
  landing_nav_get_started_clicked: {
    description: 'Landing: clicked the top-right "Sign in" button.',
  },
  landing_hero_cta_clicked: { description: 'Landing: clicked the primary hero CTA.' },
  landing_pricing_section_viewed: {
    description: 'Landing: the pricing section scrolled into view.',
  },
  landing_pricing_cta_clicked: {
    description: 'Landing: clicked a Plan card CTA. Props: plan_key.',
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
  sidebar_user_menu_opened: { description: 'Sidebar: opened the user menu.' },
  sidebar_mobile_drawer_opened: { description: 'Mobile sidebar: opened the drawer.' },
  sidebar_mobile_drawer_closed: {
    description: 'Mobile sidebar: closed the drawer. Props: via_backdrop.',
  },
  user_menu_account_clicked: { description: 'User menu: clicked "Account".' },
  user_menu_billing_clicked: { description: 'User menu: clicked "Billing".' },
  user_menu_theme_changed: {
    description: 'User menu: changed the theme. Props: theme (system/light/dark).',
  },
  user_menu_logout_clicked: { description: 'User menu: clicked "Sign out".' },

  account_dialog_opened: { description: 'Account: opened the account dialog.' },
  account_dialog_closed: {
    description: 'Account: closed the account dialog. Props: unsaved_changes.',
  },
  account_profile_saved: { description: 'Account: saved profile changes. Props: fields_changed.' },
  account_profile_save_failed: {
    description: 'Account: profile save failed. Props: error_message.',
  },

  billing_dialog_opened: { description: 'Billing: opened the billing dialog. Props: source.' },
  billing_dialog_closed: { description: 'Billing: closed the billing dialog.' },
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
  post_final_copied: { description: "Home: copied a Version's Final." },
} as const satisfies Record<string, { description: string }>;

export type EventName = keyof typeof EVENTS;

export function track<E extends EventName>(event: E, properties?: Record<string, unknown>): void {
  if (!enabled) return;
  posthog.capture(event, properties);
}

export function registerSuperProperties(props: Record<string, unknown>): void {
  if (!enabled) return;
  posthog.register(props);
}
