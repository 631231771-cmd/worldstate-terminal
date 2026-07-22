# License review

## Status

Preliminary engineering review only. This document is not legal advice.

## Upstream conclusion

World Monitor is marked `AGPL-3.0-only`. World State Terminal is a modified and
network-accessible derivative distribution of that codebase, so upstream notices,
source-availability duties, and other AGPL obligations must be preserved and
reviewed before any distribution or hosted offering.

No file in this project may claim that upstream-derived code is MIT, Apache-2.0,
or another permissive license.

## New Macro Engine service

The independent service is currently marked:

> License decision pending legal review.

This wording is a project status marker, not a license grant. A final licensing
decision must consider how the service is combined with and distributed alongside
the AGPL application.

## Intended use reviewed

- personal use;
- education and non-commercial research;
- local or private-server self-hosting.

Commercial deployment, proprietary redistribution, official branding, managed
service operation, or a closed-source integration requires a separate legal and
trademark review before release.

## Open review items

- verify every new Python package's exact distribution license and transitive
  notices from the locked environment;
- review OpenBB 4.7.2 package and provider terms before enabling each provider;
- retain source attribution and terms URLs for every external dataset;
- review generated clients and protocol artifacts as part of the combined work;
- define source-offer and network-use compliance for deployment images;
- perform a trademark review for the World Monitor and World State Terminal names.
