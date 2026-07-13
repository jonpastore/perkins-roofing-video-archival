# DDD: Knowify Contacts + Properties Backfill

## Mapping
- Knowify Client `Id` -> Customer `knowify_customer_id`.
- Client `ContactName`/`Email`/`PhoneNumberMobile|PhoneNumber` -> synthetic primary Contact with `knowify_contact_id = client:<Id>:primary`.
- Knowify Contact `Id` -> Contact `knowify_contact_id`.
- Project `Address1`/`City`/`StateProvince`/`Zip` -> Property linked through Project `ClientId`.
- Client address fields -> fallback Property if no matching property exists.

## Idempotency
- Contacts upsert by `knowify_contact_id`; synthetic contacts use a reserved string key.
- Properties update existing address-equivalent row instead of inserting duplicates.

## Safety
- Skip records missing required source keys or required property address fields.
- Never create measurements from Knowify because the `Roofs` table is empty.
