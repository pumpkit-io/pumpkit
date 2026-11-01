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
  landing_video_played: {
    description:
      'Landing: the hero launch video started playing for the first time. Props: trigger (autoplay | visitor).',
  },
  landing_video_sound_turned_on: { description: "Landing: turned the launch video's sound on." },
  landing_video_scrubbed: { description: "Landing: moved the launch video's scrubber." },
  landing_video_watched_again: {
    description: 'Landing: clicked "Watch again" at the end of the launch video.',
  },
  landing_authors_section_viewed: {
    description: 'Landing: the authors section first scrolled into view.',
  },
  landing_pricing_section_viewed: {
    description: 'Landing: the pricing section scrolled into view.',
  },
  landing_pricing_plan_viewed: {
    description:
      'Landing: a Plan first seen on the pricing card, once per Plan: the shown Plan when the card first scrolls into view, the other when the visitor first switches to it after that. Props: plan_key.',
  },
  landing_pricing_toggle_switched: {
    description:
      'Landing: switched the pricing card between Monthly and Annual. Props: interval (monthly | annual).',
  },
  landing_pricing_cta_clicked: {
    description: 'Landing: clicked the "Get started" button at the end of the pricing section.',
  },
  landing_nav_github_clicked: {
    description: 'Landing: clicked the GitHub header button. Props: surface (desktop | mobile).',
  },
  landing_open_source_section_viewed: {
    description: 'Landing: the open-source section first scrolled into view.',
  },
  landing_open_source_github_clicked: {
    description: 'Landing: clicked "View on GitHub" in the open-source section.',
  },
  landing_open_source_self_hosting_clicked: {
    description: 'Landing: clicked "Self-hosting guide" in the open-source section.',
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
  account_x_photo_used: {
    description: 'Account: made the X account\'s photo the Photo with "Use photo from X".',
  },

  paywall_viewed: { description: 'Paywall (/subscribe): shown to a User who is not Subscribed.' },
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
  top_up_checkout_started: {
    description: 'Billing: paid for a Top-up in the Buy top-up dialog, starting its checkout.',
  },
  top_up_bought: {
    description: 'Billing: returned from Stripe via the Top-up success URL.',
  },
  billing_subscribe_now_confirmed: {
    description:
      'Billing: a Trial User confirmed Subscribe now and the Trial ended, from the Usage card or a limit notice.',
  },

  // Onboarding (/onboarding)
  onboarding_step_viewed: {
    description: 'Onboarding: a step was shown. Props: step (x_connection | persona).',
  },
  onboarding_finished: {
    description:
      'Onboarding: pressed Continue on the last step and Onboarding was recorded as finished.',
  },

  // Writing: Persona, New post and the Post page
  inspiration_author_added: {
    description: 'Persona: added an Inspiration author and its posts were fetched.',
  },
  inspiration_author_removed: { description: 'Persona: removed an Inspiration author.' },
  author_looked_up: {
    description:
      'Author picker: chose "Look up @… on X" and the add answered. Props: result (found | missing | private | no_posts | limited).',
  },
  inspiration_authors_refreshed: {
    description: 'Persona: refreshed an Inspiration author and its latest posts were fetched.',
  },
  post_version_requested: {
    description:
      'New post (brief) or the Post page (feedback): asked for a Version. Props: kind (brief | feedback).',
  },
  post_version_failed: {
    description:
      'New post (brief) or the Post page (feedback): writing a Version failed. Props: kind (brief | feedback).',
  },
  allowance_used_up: {
    description:
      'New post or the Post page: an action was refused for want of Allowance. Props: ran_out (generations | x_posts | link_x_posts).',
  },
  post_text_edited: {
    description:
      "Post page: saved a burst of the User's edits to the Post's Text, once however many retries it took. Props: format (post | thread), part_count (number).",
  },
  text_undone: {
    description:
      "Post page: undid one step of the Post's Text with the undo button or ⌘Z. Props: step (edit | rewrite | restore).",
  },
  text_redone: {
    description:
      "Post page: redid one step of the Post's Text with the redo button or ⇧⌘Z. Props: step (edit | rewrite | restore).",
  },
  redo_rewrites_dropped: {
    description:
      'Post page: an edit after an undo dropped rewrites from redo, which stay in History. Props: count (number).',
  },
  version_restored: {
    description:
      "Post page: made an earlier Version the Post's Text again. Props: source (history | undo).",
  },
  post_final_copied: {
    description:
      "Post page: copied the text on screen with the card's copy icon, every Part of it.",
  },

  // Posting to X (the Post page and Settings) + the X callback
  x_connected: { description: 'Settings: connected an X account through X consent screen.' },
  x_disconnected: { description: 'Settings: disconnected the X account.' },
  x_photo_offer_shown: {
    description: "Settings: asked a User with no Photo whether to use the X account's photo.",
  },
  x_photo_offer_accepted: {
    description: "Settings: made the X account's photo the Photo from the X photo offer.",
  },
  x_photo_offer_declined: {
    description: 'Settings: answered the X photo offer with Not now, Escape or the close control.',
  },
  community_looked_up: {
    description:
      'Post to… or the inline edit: looked up a Community pasted by its URL or ID. Props: found (boolean), named (boolean, only when found).',
  },
  scheduled_post_created: {
    description:
      "Post page: created a Scheduled post from the Post's Text. Props: format (post | thread), part_count (number), source (always final: copied from the Text), post_now (boolean), destination (profile | community), share_with_followers (boolean, only for a Community).",
  },
  // Tracked by the backend, which alone sees the outcome; listed here to keep one catalog.
  scheduled_post_published: {
    description:
      'Publisher or Post now: X published every Part of a Scheduled post. Props: format (post | thread), part_count (number), source (always final: copied from the Text), destination (profile | community), share_with_followers (boolean, only for a Community).',
  },
  scheduled_post_failed: {
    description:
      'Publisher or Post now: a Scheduled post Failed. Props: format (post | thread), part_count (number), reason (not_subscribed | x_account_changed | reconnect_needed | x_unavailable | refused_by_x | outcome_unknown).',
  },
} as const satisfies Record<string, { description: string }>;

export type EventName = keyof typeof EVENTS;

export function track<E extends EventName>(event: E, properties?: Record<string, unknown>): void {
  captureEvent(event, properties);
}
