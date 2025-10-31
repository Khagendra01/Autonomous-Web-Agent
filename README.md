Very short read me written by hand



##Design Choices
GRPC server for microservices call inbetween the server program
Langgraph for controlled flow of the instruction
Gpt-4o for model because this is enough and still faster than 5, while inferencing.

for account with login credential we will save the login by running script/record_cookies to the chrome-user profile, and that will be set along with the request

## Start the Playwright Driver server
python -m src.drivers.grpc_playwright_server