"""Server-rendered shell for human account access and credential replacement.

The production and Demo routes share this markup.  Only transport/session
authority is injected by the bootstrap script.  Signed-out protected routes use
the bounded pre-auth variant so no tenant-derived or operational UI is emitted.
"""

from html import escape

from .credential_guidance import COMPANY_MASTER_DEFAULT_SECRET_PATH


def _field(label, name, input_type="text", autocomplete="off", required=True, extra=""):
    required_attribute = " required" if required else ""
    return (
        '<label class="human-access-field"><span>%s</span>'
        '<input type="%s" name="%s" autocomplete="%s"%s %s></label>'
        % (
            escape(label),
            escape(input_type, quote=True),
            escape(name, quote=True),
            escape(autocomplete, quote=True),
            required_attribute,
            extra,
        )
    )


def _company_master_guidance_markup(context):
    heading_id = "company-master-guidance-%s" % context
    return """
<aside class="human-access-credential-guide" aria-labelledby="{heading_id}">
  <p class="eyebrow">Credential help</p>
  <h3 id="{heading_id}">Where do I get the company master credential?</h3>
  <p>MemoryEndpoints creates it on <a href="/agent-setup">Agent Setup</a> and shows it once after the first company workspace is created. Setup must then write the credential file; displaying this path does not create the file. It is not your account password or an agent invitation credential.</p>
  <p><strong>Default agent-readable location</strong><code class="human-access-secret-path">&lt;project-root&gt;/{default_path}</code></p>
  <p>If you cannot find it, ask your top-level AI agent to check that exact project-relative file and run <code>scripts/recover_memoryendpoints_company_master.py</code> when it is missing. A company-scoped top-level agent can create and persist the human-operator credential there without exposing it in chat. Lower-scoped agents must ask a top-level agent or human administrator for help.</p>
</aside>
""".format(
        heading_id=escape(heading_id, quote=True),
        default_path=escape(COMPANY_MASTER_DEFAULT_SECRET_PATH),
    )


def _authentication_markup():
    return """
<div class="human-access-auth-grid" data-human-access-locked>
  <section class="human-access-card" aria-labelledby="human-login-title">
    <p class="eyebrow">Returning human</p>
    <h2 id="human-login-title">Sign in to your account</h2>
    <p>Your account remembers company memberships. Raw company master credentials are never used as login credentials.</p>
    <form data-human-access-login-form>
      {login_username}
      {login_password}
      <button class="button primary" type="submit">Sign in securely</button>
    </form>
  </section>
  <section class="human-access-card" aria-labelledby="human-enroll-title">
    <p class="eyebrow">First company owner</p>
    <h2 id="human-enroll-title">Prove ownership, then create an account</h2>
    <p>The raw company master credential is cleared before the proof request completes and is never stored in this page.</p>
    {master_guidance}
    <form data-human-access-master-proof-form>
      {master}
      <button class="button" type="submit">Prove company ownership</button>
    </form>
    <div class="human-access-account-step" data-human-access-account-step hidden>
      <form data-human-access-account-form>
        {account_username}
        {display_name}
        {account_password}
        {password_confirmation}
        <button class="button primary" type="submit">Create owner account</button>
      </form>
    </div>
  </section>
</div>
""".format(
        login_username=_field("Username", "username", autocomplete="username"),
        login_password=_field("Password", "password", "password", "current-password"),
        master=_field(
            "Company master credential",
            "companyMasterTokenSecret",
            "password",
            "off",
            extra='spellcheck="false" data-human-access-secret-control',
        ),
        master_guidance=_company_master_guidance_markup("enrollment"),
        account_username=_field("Username", "username", autocomplete="username"),
        display_name=_field("Display name", "displayName", autocomplete="name", required=False),
        account_password=_field("Password", "password", "password", "new-password"),
        password_confirmation=_field(
            "Confirm password", "passwordConfirmation", "password", "new-password"
        ),
    )


def _protected_markup(demo=False):
    demo_label = "" if not demo else "Demo — session-only mock data. Nothing on this page is a real credential."
    return """
<section class="human-access-protected" data-human-access-protected hidden>
  <div class="human-access-demo-label" data-human-access-demo-label hidden>{demo_label}</div>
  <div class="human-access-toolbar" aria-label="Human account controls">
    <form data-human-access-membership-form>
      <label class="human-access-field compact"><span>Active company</span>
        <select name="authorityId" data-human-access-membership-list></select>
      </label>
      <button class="button" type="submit">Switch company</button>
    </form>
    <div class="human-access-toolbar-actions">
      <button class="button" type="button" data-human-access-link-company>Link company</button>
      <button class="button" type="button" data-human-access-roster-refresh>Refresh roster</button>
      <button class="button quiet" type="button" data-human-access-logout>Sign out</button>
    </div>
  </div>
  <section class="human-access-card human-access-agent-master-setting" aria-labelledby="human-agent-master-setting-title">
    <div class="human-access-section-heading">
      <div><p class="eyebrow">Company security</p><h2 id="human-agent-master-setting-title">Top-level agent credential recovery</h2></div>
    </div>
    <p>Enabled by default so a company-scoped top-level agent can create the standard human-operator company master without human interaction. Disable this to require an existing company master for recovery.</p>
    <form data-human-access-agent-master-setting-form>
      <label class="human-access-check"><input type="checkbox" data-human-access-agent-master-setting> Allow top-level agents to create a human-operator company master.</label>
      <button class="button" type="submit">Save security setting</button>
      <span class="human-access-live" data-human-access-agent-master-setting-status aria-live="polite"></span>
    </form>
  </section>
  <section class="human-access-card human-access-roster" aria-labelledby="human-roster-title">
    <div class="human-access-section-heading">
      <div><p class="eyebrow">Metadata only</p><h2 id="human-roster-title">Humans and one-agent credentials</h2></div>
      <p>Existing raw credentials can never be viewed. Replace a credential to reveal one new successor once.</p>
    </div>
    <div data-human-access-roster-empty>No agent credentials are available for this company.</div>
    <div class="human-access-roster-list" data-human-access-roster-list></div>
  </section>
</section>

<dialog class="human-access-dialog" data-human-access-reauth-dialog aria-labelledby="human-reauth-title">
  <form method="dialog" data-human-access-reauth-form>
    <p class="eyebrow">Recent verification required</p>
    <h2 id="human-reauth-title">Re-enter your password</h2>
    <p>This rotates the protected session before a company link or credential replacement.</p>
    {reauth_password}
    <div class="human-access-dialog-actions">
      <button class="button quiet" type="button" data-human-access-reauth-cancel>Cancel</button>
      <button class="button primary" type="submit">Verify and continue</button>
    </div>
  </form>
</dialog>

<dialog class="human-access-dialog" data-human-access-link-dialog aria-labelledby="human-link-title">
  <form method="dialog" data-human-access-link-proof-form>
    <p class="eyebrow">Link another company</p>
    <h2 id="human-link-title">Prove the company master credential</h2>
    <p>The raw value is cleared before the proof response and is never sent to the link endpoint.</p>
    {link_master_guidance}
    {link_master}
    <div class="human-access-dialog-actions">
      <button class="button quiet" type="button" data-human-access-link-cancel>Cancel</button>
      <button class="button primary" type="submit">Prove and link</button>
    </div>
  </form>
</dialog>

<dialog class="human-access-dialog human-access-replacement" data-human-access-replacement-dialog aria-labelledby="human-replacement-title">
  <form method="dialog">
    <p class="eyebrow">Two-phase credential replacement</p>
    <h2 id="human-replacement-title">Replace and reveal a new token once</h2>
    <p data-human-access-replacement-summary></p>
    <p class="human-access-live" data-human-access-replacement-status aria-live="polite"></p>
    <label class="human-access-field"><span>One-time successor</span>
      <input type="password" readonly spellcheck="false" autocomplete="off" data-human-access-successor-token data-human-access-secret-control>
    </label>
    <div class="human-access-dialog-actions wrap">
      <button class="button" type="button" data-human-access-successor-show>Show / hide</button>
      <button class="button" type="button" data-human-access-successor-copy>Copy successor</button>
      <button class="button quiet" type="button" data-human-access-successor-clear>Clear reveal</button>
    </div>
    <label class="human-access-check"><input type="checkbox" data-human-access-successor-saved> I saved the successor outside this page.</label>
  </form>
  <form data-human-access-possession-form>
    <label class="human-access-field"><span>Paste saved successor to prove possession</span>
      <input type="password" name="successorTokenProof" autocomplete="off" spellcheck="false" data-human-access-possession-token data-human-access-secret-control>
    </label>
    <div class="human-access-dialog-actions wrap">
      <button class="button primary" type="submit">Confirm atomic replacement</button>
      <button class="button" type="button" data-human-access-replacement-retry>Check status</button>
      <button class="button danger" type="button" data-human-access-replacement-cancel>Cancel replacement</button>
    </div>
  </form>
</dialog>
""".format(
        demo_label=escape(demo_label),
        reauth_password=_field("Account password", "password", "password", "current-password"),
        link_master=_field(
            "Company master credential",
            "companyMasterTokenSecret",
            "password",
            "off",
            extra='spellcheck="false" data-human-access-secret-control',
        ),
        link_master_guidance=_company_master_guidance_markup("link-company"),
    )


def render_human_access_main(authenticated=False, demo=False):
    preauth = not authenticated and not demo
    attributes = ["data-human-access"]
    if preauth:
        attributes.extend(["data-human-preauth-shell", "data-human-access-preauth-only"])
    if demo:
        attributes.append("data-human-access-demo")
    demo_warning = ""
    if demo:
        demo_warning = """
  <aside class="human-access-demo-warning" data-human-access-demo-warning role="note" aria-label="Demo credential safety">
    <strong>DEMO - session-only mock data</strong>
    <span>Never enter a real username, password, company master credential, recovery secret, or agent token. Use invented demo values only; nothing is sent to protected APIs.</span>
  </aside>
"""
    protected = "" if preauth else _protected_markup(demo=demo)
    return """
<section class="human-access human-access-shell" {attributes}>
  {demo_warning}
  <header class="human-access-hero">
    <p class="eyebrow">Human authority</p>
    <h1>Secure access that remembers your companies—not their master credentials</h1>
    <p>Create one human account, explicitly link company authority, and manage redacted one-agent credential metadata without exposing an existing token.</p>
  </header>
  <div class="human-access-status" data-human-access-status role="status" aria-live="polite" tabindex="-1"></div>
  {authentication}
  {protected}
</section>
""".format(
        attributes=" ".join(attributes),
        demo_warning=demo_warning,
        authentication=_authentication_markup(),
        protected=protected,
    )
