import Chat from "../models/Chat";


//create a new chat
export const createChat = async (req,res)=>{
    try{
        const userId = req.user._id;
        const userName = req.user.fullName;

        const chatData ={
            userId,
            messages:[],
            name:"New Chat",
            userName
        }
        await Chat.create(chatData);
        res.status(201).json({message:"Chat created successfully"})
    }
    catch(error){
        res.json({message:error.message})
    }
}


// to get all the chats
export const getchats = async (req,res)=>{
    try{
        const userId = req.user._id;
        const chats = await Chat.find({userId}).sort({updatedAt:-1});
        res.status(200).json(chats);
    }catch(error){
        res.json({message:error.message})
    }
}


// to delete a chat
export const deletechat = async (req,res)=>{
    try{
        const userId = req.user._id;
        const {chatId} = req.body;

        await Chat.deleteOne({_id:chatId,userId});
        res.status(200).json({message:"Chat deleted successfully"})
    }catch(error){
        res.json({message:error.message})
    }
}
