import asyncio
from app.services.location_service import get_talukas, get_villages
from app.services.job_manager import job_manager

async def run():
    print("LIVE LOCATION METADATA CHECK\\n")
    
    # Pune district portal value is '25'
    district_text = "पुणे"
    district_value = "25"
    
    print(f"District:\\n{district_text}")
    print(f"District portal value:\\n{district_value}\\n")
    
    talukas = await get_talukas(district_value)
    print(f"Taluka count:\\n{len(talukas)}")
    print("First up to 10 Talukas:")
    for t in talukas[:10]:
        print(f"{t.text} | {t.value}")
    print()
    
    # Select first taluka
    selected_taluka = talukas[0]
    print(f"Selected Taluka:\\n{selected_taluka.text}")
    print(f"Selected Taluka portal value:\\n{selected_taluka.value}\\n")
    
    villages = await get_villages(district_value, selected_taluka.value)
    print(f"Village count:\\n{len(villages)}")
    print("First up to 10 Villages:")
    for v in villages[:10]:
        print(f"{v.text} | {v.value}")
    print()

if __name__ == "__main__":
    asyncio.run(run())
