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

    dc=example,dc=net
    ├── cn=users
    │   ├── uid=admin
    │   ├── uid=thomas
    │   └── ...
    ├── cn=groups
    └── cn=synoconf

Variables

  Variable                  Description                 Default
  ------------------------- --------------------------- ------------------------------
  ldap_host                 LDAP server hostname        ldap.example.net
  ldap_port                 LDAP port                   389
  ldap_protocol             LDAP protocol               ldap
  ldap_base_dn              Directory base DN           dc=example,dc=net
  ldap_search_base          User search base            cn=users,dc=example,dc=net
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
        ldap://ldap.example.net:389

    Base DN:
        dc=example,dc=net

    Search base:
        cn=users,dc=example,dc=net

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

