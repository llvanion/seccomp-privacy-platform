This dataset contains information about sponsored search conversion dataset. It contains information about the product related advertisements a user has clicked and possibly converted (i.e. sale has occurred). □The products were shown to the user, once the user has expressed his/her intent via a search query. This datasets provides a platform to analyze new set of applications in the world of conversion modeling for online search advertising.

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Content of this dataset

Header Information :
<Sale> ,<SalesAmountInEuro> ,<time_delay_for_conversion>, <click_timestamp> ,<nb_clicks_1week> ,<product_price> ,<product_age_group> ,<device_type>,<audience_id> ,<product_gender> ,<product_brand> ,<product_category(1-7)> ,<product_country>, <product_id> ,<product_title> ,<partner_id> ,<user_id>

This dataset includes following files:

README.md
Criteo_Conversion_Search.tsv.gz:
Data description

This dataset represents a sample of 90 days of Criteo live traffic data. Each line corresponds to one click (product related advertisement) that was displayed to a user. For each advertisement, we have detailed information about the product. Further, we also provide information on whether the click led to a conversion, amount of conversion and the time between the click and the conversion. □Data has been sub-sampled and anonymized so as not to disclose proprietary elements.

Delimited: \t (tab separated)

Missing Value Indicator: -1 for all other fields. 0 indicates missing for field click_timestamp

Outcome/Labels

Sale□: Indicates 1 if conversion occurred and 0 if not).
SalesAmountInEuro : Indicates□the revenue obtained when a conversion took place. This might be different from product-price, due to attribution issues. It is -1, when no conversion took place.
Time_delay_for_conversion : This indicates the time between click and conversion.□It is -1, when no conversion took place.
Features

click_timestamp: Timestamp of the click. The dataset is sorted according to timestamp.
nb_clicks_1week: Number of clicks the product related advertisement has received in the last 1 week.
product_price: Price of the product shown in the advertisement.
product_age_group: The intended user age group of the user, the product is made for.
device_type: This indicates whether it is a returning user or a new user on mobile, tablet or desktop.□
audience_id: □We do not disclose the meaning of this feature.
product_gender:□The intended gender of the user, the product is made for.
product_brand: Categorical feature about the brand of the product.
product_category(1-7): Categorical features associated to the product. We do not disclose the meaning of these features.
product_country: Country in which the product is sold.
product_id: Unique identifier associated with every product.
product_title: Hashed title of the product.
partner_id: Unique identifier associated with the seller of the□product.
user_id: Unique identifier associated with every user.

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Key figures

Size uncompressed : 6.4 GB
Size compressed :


Tasks

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
This dataset can be used in a large scope of applications related to Conversion Modeling, including but not limited to:

Conversion rate modeling in sponsored search advertising.
Modeling the expected conversion revenue in sponsored search.
Survival-Analysis techniques to model the time between conversion and click.
Offline metrics for conversion prediction tasks.

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Citation

Information coming soon.
We would love to hear from you if use this data or plan to use it. Refer to the Contact section below.

----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
Contact

For any question, feel free to contact:
Criteo Research team:□http://research.criteo.com/contact-us/
Criteo Research twitter account: @CriteoResearch
Download instructions


----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
File Created by:□

Pranjul Yadav
Research Scientist at Criteo.