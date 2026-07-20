Bergen Platform LDAP role

This role configures LDAP client access for Bergen Platform services.

Currently the primary consumer is Open WebUI. Future services can reuse
the same LDAP configuration.

Responsibilities

-   install LDAP client utilities
-   validate LDAP network connectivity
-   validate directory search access
-   create the Open WebUI LDAP environment file
-   support anonymous or authenticated application binds

Current LDAP tree

    dc=bergen,dc=intern
    ├── cn=users
    │   ├── uid=admin
    │   ├── uid=thomas
    │   └── ...
    ├── cn=groups
    └── cn=synoconf

Variables

  Variable                  Description                 Default
  ------------------------- --------------------------- ------------------------------
  ldap_host                 LDAP server hostname        bergen.intern
  ldap_port                 LDAP port                   389
  ldap_protocol             LDAP protocol               ldap
  ldap_base_dn              Directory base DN           dc=bergen,dc=intern
  ldap_search_base          User search base            cn=users,dc=bergen,dc=intern
  ldap_username_attribute   Login attribute             uid
  ldap_mail_attribute       Mail attribute              mail
  ldap_bind_dn              Application Bind DN         anonymous
  ldap_bind_password        Application Bind password   anonymous

Generated files

This role creates:

/etc/bergen-platform/open-webui-ldap.env

Permissions:

-   owner: root
-   group: root
-   mode: 0600

Validation

The role validates:

-   LDAP TCP connectivity
-   LDAP directory availability
-   Search base accessibility
-   User search functionality
-   Anonymous or authenticated bind
-   Required LDAP attributes

Dependencies

This role should be executed before:

-   open_webui

Required infrastructure:

-   OpenLDAP server
-   Reachable LDAP network
-   Existing directory tree

Example

    Server:
        ldap://bergen.intern:389

    Base DN:
        dc=bergen,dc=intern

    Search base:
        cn=users,dc=bergen,dc=intern

    Username attribute:
        uid

    Mail attribute:
        mail

    Bind:
        anonymous

Future work

-   StartTLS support
-   LDAPS support
-   Certificate validation
-   Service account support
-   Group based authorization
-   Multiple search bases
-   Nested group support
-   Role mapping
-   SSO integration

